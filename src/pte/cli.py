import asyncio
import click
from dotenv import load_dotenv

load_dotenv()


@click.group()
def main():
    pass


@main.command()
@click.option("--from", "from_date", required=True, help="Start date inclusive, e.g. 2026-05-01")
@click.option("--to", "to_date", required=True, help="End date exclusive, e.g. 2026-06-01")
@click.option("--feeds", default=None, help="Comma-separated feed names or 'all'")
@click.option(
    "--method",
    default="pagination",
    type=click.Choice(["pagination", "snapshot", "db-file"], case_sensitive=False),
    show_default=True,
    help=(
        "pagination: cursor-paginated REST API (reliable, recommended). "
        "snapshot: ThreatStream Snapshot bulk export (may time out for large orgs). "
        "db-file: load files supplied by the data team (place in data/db_export/ or use --db-export-dir)."
    ),
)
@click.option(
    "--db-export-dir",
    default=None,
    help="Path to directory containing data-team export files. Only used with --method db-file. Defaults to data/db_export/.",
)
@click.option("--format", "fmt", default="json_v2", hidden=True)
@click.option(
    "--max-observables",
    default=None,
    type=int,
    help="Cap observable pull at this many records. Pages checkpoint to disk every 50k. Pagination method only.",
)
def ingest(from_date, to_date, feeds, method, db_export_dir, fmt, max_observables):
    """Pull ThreatStream data into a frozen corpus.

    Three methods are available:\n
    \b
      pagination  Cursor-paginated REST API. Reliable. Recommended default.
      snapshot    ThreatStream Snapshot bulk export. May time out for large orgs.
      db-file     Load files provided by the data team from data/db_export/.
    """
    from pte.gateway.threatstream import ThreatStreamClient
    from pte.ingest.frozen_batch import FrozenBatchRunner

    feed_list = feeds.split(",") if feeds and feeds != "all" else None

    if method == "db-file":
        # db-file doesn't need a live ThreatStream connection for data pull,
        # but we still construct a client for the sizing calibration step.
        # Pass db_export_dir through via a separate runner invocation.
        import json
        from pathlib import Path
        from pte.ingest.db_file_ingestor import DatabaseFileIngestor
        from pte.ingest.raw_store import RawStore
        from pte.common.provenance import make_run_id, config_hash
        from pte.common.logging import progress, structured_log

        run_id = make_run_id()
        cfg = {"from": from_date, "to": to_date, "feeds": feed_list, "method": method}
        batch_id = f"{run_id[:8]}-{config_hash(cfg)}"
        data_dir = Path("data")
        store = RawStore(base_dir=str(data_dir / "raw"))
        db_dir = db_export_dir or str(data_dir / "db_export")

        async def run_db():
            progress("=== PTE Ingest (db-file) ===",
                     batch_id=batch_id, from_date=from_date, to_date=to_date)
            progress("Step 1/4  Sizing calibration skipped (no live API in db-file mode)")
            ingestor = DatabaseFileIngestor(store, data_dir, db_export_dir=db_dir)
            stats = await ingestor.run(batch_id, from_date, to_date)
            progress("Step 4/4  Writing manifest...")
            manifest = {
                "batch_id": batch_id, "run_id": run_id,
                "from_date": from_date, "to_date": to_date,
                "method": method, "config_hash": config_hash(cfg), **stats,
            }
            frozen_dir = data_dir / "frozen" / batch_id
            frozen_dir.mkdir(parents=True, exist_ok=True)
            (frozen_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
            structured_log("batch_complete", batch_id=batch_id, manifest=manifest)
            total_dedup = stats.get("total_deduplicated")
            progress("=== Batch complete ===", batch_id=batch_id,
                     observables=f"{total_dedup:,}" if isinstance(total_dedup, int) else "?",
                     method=method)
            return batch_id

        result_id = asyncio.run(run_db())
        click.echo(f"Batch complete: {result_id}")
    else:
        ts = ThreatStreamClient()
        runner = FrozenBatchRunner(ts_client=ts)
        batch_id = asyncio.run(
            runner.run(from_date=from_date, to_date=to_date,
                       feeds=feed_list, fmt=fmt, method=method,
                       max_observables=max_observables)
        )
        click.echo(f"Batch complete: {batch_id}")


@main.command()
@click.option("--discover", is_flag=True)
@click.option("--extract", is_flag=True)
@click.option("--batch-id", required=True)
def convert(discover, extract, batch_id):
    """Run conversion (discovery and/or extraction) on a frozen batch."""
    from pte.convert.pipeline import ConversionPipeline
    pipeline = ConversionPipeline(batch_id=batch_id)
    if discover:
        asyncio.run(pipeline.run_discovery())
    if extract:
        asyncio.run(pipeline.run_extraction())


@main.group()
def features():
    pass


@features.command("build")
@click.option("--batch-id", required=True)
def features_build(batch_id):
    """Build the tier-aware feature store for a batch."""
    from pte.features.build import FeatureBuilder
    builder = FeatureBuilder(batch_id=batch_id)
    asyncio.run(builder.build())


@main.command()
@click.argument("task")
@click.option("--batch-id", required=True)
def train(task, batch_id):
    """Fit a prediction model for a task on a batch."""
    from pte.predict.base import get_task
    t = get_task(task, batch_id=batch_id)
    t.fit()
    click.echo(f"Trained {task}")


@main.command()
@click.argument("task")
@click.option("--batch-id", required=True)
def evaluate(task, batch_id):
    """Evaluate a prediction model and write the report."""
    from pte.predict.base import get_task
    t = get_task(task, batch_id=batch_id)
    report = t.evaluate()
    click.echo(f"Evaluation report: {report}")
