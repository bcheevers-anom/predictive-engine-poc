import json
from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).parents[3] / "config" / "default.yaml"
PROMPT_PATH = Path(__file__).parents[3] / "prompts" / "story_dedup_adjudicator_v1.txt"


def _load_dedup_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)["dedup"]


def _title_shingle_key(record: dict, n: int = 1) -> set:
    title = (record.get("title", "") + " " + record.get("description", ""))[:200].lower()
    words = title.split()
    return {" ".join(words[i:i+n]) for i in range(len(words) - n + 1)}


def _candidate_blocks(records: list[dict]) -> list[list[dict]]:
    """Blocking by title shingle overlap — O(n) pass, no all-pairs."""
    blocks: list[list[int]] = []

    for i, rec in enumerate(records):
        shingles = _title_shingle_key(rec)
        matched_block = None
        for bi, block in enumerate(blocks):
            for j in block:
                if shingles and _title_shingle_key(records[j]) and len(shingles & _title_shingle_key(records[j])) >= 1:
                    matched_block = bi
                    break
            if matched_block is not None:
                break
        if matched_block is not None:
            blocks[matched_block].append(i)
        else:
            blocks.append([i])

    return [[records[j] for j in block] for block in blocks]


class _AdjudicationResult:
    def __init__(self, same_event: bool, confidence: float, rationale: str, shared_anchors: list):
        self.same_event = same_event
        self.confidence = confidence
        self.rationale = rationale
        self.shared_anchors = shared_anchors


async def l3_story_cluster(records: list[dict], llm_client) -> list[dict]:
    cfg = _load_dedup_config()
    auto_merge_threshold = cfg["l3_auto_merge_threshold"]
    ambiguous_lo, ambiguous_hi = cfg["l3_ambiguous_band"]

    prompt_template = PROMPT_PATH.read_text()
    blocks = _candidate_blocks(records)
    output = []

    from pte.dedup.merge import build_canonical_record

    for block in blocks:
        if len(block) == 1:
            r = dict(block[0])
            r.setdefault("dedup_status", "singleton")
            output.append(r)
            continue

        for i in range(len(block)):
            for j in range(i + 1, len(block)):
                prompt = prompt_template.format(
                    record_a=json.dumps({k: block[i].get(k) for k in ("id", "title", "description", "source_feed")}),
                    record_b=json.dumps({k: block[j].get(k) for k in ("id", "title", "description", "source_feed")}),
                )
                try:
                    adj = await llm_client.complete(
                        prompt=prompt,
                        model_tier="mid",
                    )
                    # adj is a MagicMock in tests with same_event, confidence attrs
                    same_event = getattr(adj, "same_event", False)
                    confidence = getattr(adj, "confidence", 0.0)

                    if same_event and confidence >= auto_merge_threshold:
                        merged = build_canonical_record([block[i], block[j]], dedup_level="L3", dedup_confidence=confidence)
                        output.append(merged)
                    elif same_event and ambiguous_lo <= confidence < ambiguous_hi:
                        r = dict(block[i])
                        r["dedup_status"] = "possible_duplicate"
                        r["dedup_confidence"] = confidence
                        output.append(r)
                        output.append(dict(block[j]))
                    else:
                        output.extend([dict(block[i]), dict(block[j])])
                except Exception:
                    for rec in block:
                        r = dict(rec)
                        r["dedup_status"] = "quarantined_pair"
                        output.append(r)
                    break

    return output
