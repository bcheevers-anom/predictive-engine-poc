# Skill: entity_extraction

**Version:** v1  
**Model tier:** strong  
**Type:** LLM-heavy, schema-constrained  
**Purpose:** Extract industry, company, geography, tool, tactic, and technique from free-text and HTML entity descriptions into the PTEEntity schema.

## Inputs
- Full `description` body of a single ThreatStream entity (actor, campaign, malware, tool, vulnerability)
- The entity's `entity_id`, `entity_type`, `source_feed`, known `stix_id`
- The run's `run_id`

## Outputs
A `PTEEntity`-shaped dict with `tier = "LLM_EXTRACTED"` on all extracted fields.

## Failure modes
On Pydantic validation failure: `quarantine.add(entity_id, reason, context)` — never silently drop.  
On LLMError: retry once; on second failure: quarantine.

## Prompt reference
`prompts/entity_extraction_v1.txt`

## Subagent decomposition
For documents exceeding `config.convert.subagent_threshold` chars, may decompose into facet sub-extractions (industry, TTPs, company/identity). A failed facet quarantines only that facet; the partial record is flagged `validation_status = "partial"`.
