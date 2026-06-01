# Skill: blob_discovery

**Version:** v1  
**Model tier:** strong  
**Type:** LLM-heavy  
**Purpose:** Profile a sample of ThreatStream entity description blobs to discover what intelligence signal (industry, company, tool, tactic, technique, date) exists and in what proportion.

## Inputs
- A sample of `description` HTML/text blobs from a single feed+entity-type slice
- The `batch_id` and `run_id` for provenance

## Outputs
`data/coverage/<batch_id>/discovery_<feed>_<type>.json`

## Validation
- `sample_size` must equal the number of blobs actually processed
- All presence rates in [0.0, 1.0]; all confidence means in [0.0, 1.0]
- Quarantine count must reconcile: quarantine_count + processed_count = sample_size

## Prompt reference
`prompts/blob_discovery_v1.txt`

## Data-parallel execution
Run as N workers over feed/type shards via `gateway/concurrency.py`. Each worker handles one shard and writes a keyed output file. Stage complete when all shard keys present.
