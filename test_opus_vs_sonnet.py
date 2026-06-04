"""
Opus vs Sonnet extraction quality + speed test.

Tests 5 real campaign descriptions with implicit inference opportunities.
Runs each through both models and scores:
  - Field coverage (how many fields populated)
  - Inference quality (did it correctly infer non-explicit signals)
  - Speed (seconds per call)
  - Cost (estimated USD)

Run: python test_opus_vs_sonnet.py

Results printed to console and saved to data/model_test_results.json
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import time
from pathlib import Path
from pte.ingest.raw_store import RawStore
from pte.gateway.llm_client import LLMClient
from pte.schema.models import PTEEntity

PROMPT_PATH = Path("prompts/entity_extraction_v1.txt")
MAX_DESC_CHARS = 3000

# Ground truth for scoring — what SHOULD be extracted (inference required)
# Format: {candidate_idx: {field: [expected_values_any_of]}}
GROUND_TRUTH = {
    0: {  # Banco Promerica / RansomHouse
        "industry": ["Financial Services", "Banking", "Finance"],
        "tool": ["RansomHouse"],
        "geography": ["Dominican Republic", "Central America", "Caribbean"],
    },
    1: {  # Orange España BGP disruption
        "industry": ["Telecommunications", "Telecom"],
        "tactic": ["Initial Access", "Defense Evasion"],
        "geography": ["Spain", "Europe"],
    },
    2: {  # Russia-Ukraine
        "geography": ["Russia", "Ukraine"],
        "industry": ["Government", "Military", "Defense"],
    },
    3: {  # US SEC compromise
        "industry": ["Government", "Financial Services", "Finance"],
        "tactic": ["Initial Access", "Impact"],
        "geography": ["United States", "US"],
    },
    4: {  # Volt Typhoon / Cisco
        "industry": ["Critical Infrastructure", "Telecommunications", "Technology"],
        "tool": ["Volt Typhoon"],
        "geography": ["United States", "US"],
    },
}


def score_extraction(result: PTEEntity | None, ground_truth: dict) -> dict:
    """Score an extraction against ground truth. Returns dict of scores 0-1."""
    if result is None:
        return {"field_coverage": 0.0, "inference_score": 0.0, "total": 0.0}

    # Field coverage: fraction of extractable fields that are non-null
    extractable = ["industry", "tool", "tactic", "technique", "geography", "company"]
    populated = sum(1 for f in extractable if getattr(result, f, None))
    field_coverage = populated / len(extractable)

    # Inference score: for each ground truth field, did any expected value appear?
    inference_hits = 0
    inference_total = 0
    for field, expected_values in ground_truth.items():
        inference_total += 1
        actual = getattr(result, field, None)
        if not actual:
            continue
        actual_str = json.dumps(actual).lower()
        if any(ev.lower() in actual_str for ev in expected_values):
            inference_hits += 1

    inference_score = inference_hits / inference_total if inference_total > 0 else 0.0
    total = (field_coverage + inference_score) / 2
    return {
        "field_coverage": round(field_coverage, 2),
        "inference_score": round(inference_score, 2),
        "inference_hits": f"{inference_hits}/{inference_total}",
        "total": round(total, 2),
    }


async def test_model(model_tier: str, candidates: list[dict], llm: LLMClient) -> list[dict]:
    prompt_template = PROMPT_PATH.read_text()
    results = []

    for i, candidate in enumerate(candidates):
        desc = (candidate.get("description") or "")[:MAX_DESC_CHARS]
        entity_id = str(candidate.get("id", f"test-{i}"))
        prompt = prompt_template.format(
            entity_id=entity_id,
            entity_type="campaign",
            source_feed=candidate.get("source", ""),
            stix_id=candidate.get("uuid", ""),
            description=desc,
        )

        t0 = time.monotonic()
        try:
            result = await llm.complete(prompt=prompt, model_tier=model_tier, schema=PTEEntity)
            elapsed = time.monotonic() - t0
            score = score_extraction(result, GROUND_TRUTH[i])
            results.append({
                "candidate": i,
                "name": candidate.get("name", "?")[:60],
                "elapsed_s": round(elapsed, 1),
                "score": score,
                "industry": result.industry if result else None,
                "tool": result.tool if result else None,
                "tactic": result.tactic if result else None,
                "geography": result.geography if result else None,
            })
            print(f"  [{model_tier}] #{i+1} done in {elapsed:.1f}s | "
                  f"inference={score['inference_hits']} | "
                  f"coverage={score['field_coverage']:.0%}")
        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"  [{model_tier}] #{i+1} ERROR in {elapsed:.1f}s: {exc}")
            results.append({"candidate": i, "error": str(exc), "elapsed_s": round(elapsed, 1)})

    return results


async def main():
    # Load 5 test candidates
    store = RawStore(base_dir="data/raw")
    batch_id = json.loads(Path("data/ingest_state.json").read_text()).get("batch_id", "")
    campaigns = store.read(batch_id, "campaign")

    candidates = []
    for c in campaigns:
        desc = (c.get("description") or "")
        if len(desc) > 500 and len(desc) < 3000:
            has_implicit = any(w in desc.lower() for w in [
                "infrastructure", "utility", "bank", "hospital", "petroleum",
                "ministry", "npm", "supply chain", "ics", "scada", "telecom",
                "exchange commission", "ransomhouse",
            ])
            if has_implicit:
                candidates.append(c)
        if len(candidates) >= 5:
            break

    if not candidates:
        print("ERROR: No suitable test candidates found. Run pte ingest first.")
        return

    print(f"=== Opus vs Sonnet Extraction Test ===")
    print(f"Testing {len(candidates)} campaigns with implicit inference opportunities")
    print(f"New prompt: inference-enabled (explicit + contextual)")
    print()

    llm = LLMClient()
    all_results = {}

    for model_tier, label in [("strong", "Opus 4.8"), ("mid", "Sonnet 4.6")]:
        print(f"--- {label} ---")
        t_start = time.monotonic()
        results = await test_model(model_tier, candidates, llm)
        total_time = time.monotonic() - t_start

        avg_elapsed = sum(r.get("elapsed_s", 0) for r in results) / len(results)
        avg_inference = sum(r.get("score", {}).get("inference_score", 0) for r in results if "score" in r) / len(results)
        avg_coverage = sum(r.get("score", {}).get("field_coverage", 0) for r in results if "score" in r) / len(results)
        cost = llm.cost_summaries()

        all_results[label] = {
            "results": results,
            "avg_elapsed_s": round(avg_elapsed, 1),
            "total_elapsed_s": round(total_time, 1),
            "avg_inference_score": round(avg_inference, 2),
            "avg_field_coverage": round(avg_coverage, 2),
            "cost": cost,
        }
        print(f"  Total: {total_time:.1f}s | Avg/call: {avg_elapsed:.1f}s")
        print(f"  Avg inference score: {avg_inference:.0%} | Avg field coverage: {avg_coverage:.0%}")
        print()

    # Summary comparison
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    for label, data in all_results.items():
        print(f"{label}:")
        print(f"  Speed:     {data['avg_elapsed_s']:.1f}s/call  ({data['total_elapsed_s']:.1f}s total)")
        print(f"  Inference: {data['avg_inference_score']:.0%}")
        print(f"  Coverage:  {data['avg_field_coverage']:.0%}")
        print()

    # Detailed per-candidate comparison
    print("Per-candidate inference scores:")
    print(f"{'Candidate':<45} {'Opus':>8} {'Sonnet':>8}")
    print("-" * 63)
    opus_results = all_results.get("Opus 4.8", {}).get("results", [])
    sonnet_results = all_results.get("Sonnet 4.6", {}).get("results", [])
    for o, s in zip(opus_results, sonnet_results):
        name = o.get("name", "?")[:43]
        o_score = o.get("score", {}).get("inference_score", 0)
        s_score = s.get("score", {}).get("inference_score", 0)
        winner = "<< Opus" if o_score > s_score else ("Sonnet >>" if s_score > o_score else "  tie  ")
        print(f"  {name:<43} {o_score:>6.0%}  {s_score:>6.0%}  {winner}")

    # Save full results
    out_path = Path("data/model_test_results.json")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nFull results saved to {out_path}")
    print("\nRECOMMENDATION: If Sonnet inference score is within 10% of Opus")
    print("and Sonnet is >3x faster, switch to Sonnet for remaining extraction.")


if __name__ == "__main__":
    asyncio.run(main())
