# Skill: story_dedup_adjudicator

**Version:** v1  
**Model tier:** mid  
**Type:** LLM, schema-constrained  
**Purpose:** Decide whether two candidate story/event records describe the same underlying campaign/incident.

## Inputs
Two extracted-and-summarised records (NOT raw HTML).

## Outputs (schema-constrained)
`{"same_event": bool, "confidence": float, "rationale": str, "shared_anchors": [str]}`

## Validation
- `confidence` in [0.0, 1.0]
- `rationale` non-empty
- On validation failure: quarantine the pair — never auto-merge on failure.

## Bias toward caution
Only auto-merge above `config.dedup.l3_auto_merge_threshold`. Pairs in the ambiguous band → `possible_duplicate`.

## Prompt reference
`prompts/story_dedup_adjudicator_v1.txt`
