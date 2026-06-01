import asyncio
import click
from dotenv import load_dotenv

load_dotenv()


@click.group()
def main():
    pass


@main.command()
@click.option("--from", "from_date", required=True)
@click.option("--to", "to_date", required=True)
@click.option("--feeds", default=None, help="Comma-separated feeds or 'all'")
@click.option("--snapshot", is_flag=True, default=True)
@click.option("--format", "fmt", default="json_v2")
def ingest(from_date, to_date, feeds, snapshot, fmt):
    """Pull ThreatStream data into a frozen corpus."""
    from pte.gateway.threatstream import ThreatStreamClient
    from pte.ingest.frozen_batch import FrozenBatchRunner

    feed_list = feeds.split(",") if feeds and feeds != "all" else None
    ts = ThreatStreamClient()
    runner = FrozenBatchRunner(ts_client=ts)
    batch_id = asyncio.run(runner.run(from_date=from_date, to_date=to_date, feeds=feed_list, fmt=fmt))
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
