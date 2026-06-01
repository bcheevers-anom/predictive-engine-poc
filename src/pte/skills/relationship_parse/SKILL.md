# Skill: relationship_parse

**Version:** v1  
**Model tier:** fast (with light LLM cleanup)  
**Type:** deterministic + light LLM  
**Purpose:** Parse GTI campaign timelines and Mandiant actor association tables into structured SROs.

## Inputs
- Raw HTML body from a GTI campaign or Mandiant actor entity
- The feed name (to select the correct parser from `tier2_parsers/registry.py`)
- The entity's `entity_id`, `run_id`

## Outputs
List of `SRO` objects with `relationship_type`, `source_ref`, `target_ref`, `attribution_scope`, `extraction_confidence`, `provenance`.

## Validation
- All dates must parse as ISO-8601
- TTP IDs must match `T\d{4}(\.\d{3})?`
- `attribution_scope` must be in `["direct", "indirect", "suspected", "unknown"]`
- On template drift: `quarantine.add(entity_id, "template_drift", ...)` — flag for a new template

## Prompt reference
`prompts/relationship_parse_v1.txt`
