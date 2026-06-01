# Data Export Request — Predictive Threat Engine PoC

**To:** Data / Platform Engineering Team  
**From:** Barry Cheevers, Ilamona  
**Date:** 1 June 2026  
**Priority:** Medium — PoC development  
**Reference:** Predictive Threat Engine PoC (org_id 2956, `ui.threatstream.com`)

---

## Background

I am building a proof-of-concept Predictive Threat Engine that ingests intelligence from our ThreatStream instance, extracts structured signal using an LLM conversion layer, and runs predictive models to forecast threat activity by sector, tool, and tactic. The pipeline normally pulls data directly via the ThreatStream REST API. This request is a fallback in case the API route encounters issues — I need the same data exported directly from the database.

---

## What I Need

I need a one-month extract covering **1 May 2026 to 1 June 2026**, scoped to **org_id 2956** (Ilamona internal). There are two distinct data families, both required.

---

### 1. Observables / Indicators of Compromise

This is the bulk of the data. I need all active intelligence records created within the date window — everything in the `intelligence` table (or equivalent) excluding records with `status = 'falsepos'`.

For each record I need the following fields:

- **Identity:** `id`, `uuid`, `value` (the indicator itself), `type` (domain/ip/url/md5 etc.), `itype` (fine indicator type e.g. `mal_domain`, `c2_ip`, `phish_url`)
- **Scoring:** `confidence`, `source_reported_confidence`, `retina_confidence`, `severity`, `threat_type`
- **Status and lifecycle:** `status`, `expiration_ts`, `meta.detail2` (this field often contains deactivation timestamps and false-positive notes — it is critical for the training labels)
- **Source attribution:** `source` (feed name), `feed_id`
- **Geography (IP records):** `country`, `asn`, `org`, `latitude`, `longitude`
- **Timestamps:** `created_ts`, `modified_ts`, `source_created`, `source_modified`
- **Tags:** all tag names associated with each record, ideally as a list. Please exclude tags beginning with `Ilamona_` or `PIR` — these are internal workflow tags we do not need
- **TLP:** `tlp`

Approximate volume based on API counts: the full active observable corpus for this org runs to roughly 9,500 records in a snapshot. The one-month window will be a subset of that.

---

### 2. Threat Model Entities

These are the finished-intelligence objects — actors, campaigns, malware families, vulnerabilities, and MITRE ATT&CK techniques. They carry rich narrative descriptions that the LLM extraction layer processes to identify industry sectors, tools, and tactics. Volume is much smaller than observables (hundreds of records, not thousands).

For each entity type, I need:

**All five types:** Actor, Campaign, Malware, Vulnerability, Attack Pattern (MITRE technique)

For **every entity**, regardless of type, I need:
- `id`, `uuid`, `name`, `status`, `feed_id`, `tlp`
- `created_ts`, `modified_ts`, `source_created`, `source_modified`
- `target_industry` (list of targeted sector names)
- All associated tags (same exclusion rule: no `Ilamona_` or `PIR` prefixes)
- **`description`** — the full HTML/text body of the entity. This is the most important field. It contains the relationship graph, campaign timelines, actor associations, MITRE ATT&CK mappings, and IOC lists that the extraction layer parses. Please do not truncate it.

Additionally, for specific types:

- **Actor:** `aliases` (all known aliases with their IDs), `primary_motivation`, `resource_level`, `sophistication_type`
- **Campaign:** `objective`, `start_date`, `end_date`, `activity_dates`
- **Malware:** `capabilities` (the normalised behavior token list), `malware_types`, `execution_platforms`, `is_family`, `aliases`
- **Vulnerability:** `cvss2_score`, `cvss3_score`, `epss_score`, `epss_percentile` — these four numeric fields are the primary features for the vulnerability exploitation model
- **Attack Pattern:** `is_mitre` flag and the STIX ID (the `attack-pattern--<uuid>` value)

For the date filter on entities: please use `created_ts >= 2026-05-01 AND created_ts < 2026-06-01`, same as for observables.

---

### 3. Sizing Counts

Before or alongside the main export, I would find it helpful to receive a simple count per entity type — how many records exist in the date window for each of: observables, actors, campaigns, malware, vulnerabilities, attack patterns. This lets me calibrate the pipeline before processing the full extract.

---

## Format

Any of the following works well with the pipeline:

- **JSON Lines (JSONL)** — one record per line — is ideal, as the pipeline already handles this
- **JSON array** per file (one file per entity type) also works
- **CSV with a JSON column for nested fields** (tags, capabilities, aliases) is acceptable if the above are not straightforward

Please provide one file per entity type:
- `observables.jsonl`
- `campaigns.jsonl`
- `actors.jsonl`
- `malware.jsonl`
- `vulnerabilities.jsonl`
- `attack_patterns.jsonl`
- `sizing_counts.json` (a small file — just a dict of entity_type → count)

Delivery via S3, shared drive, or direct file transfer is all fine.

---

## Data Handling

This data will be used solely for the Predictive Threat Engine PoC. It will be stored locally on a full-disk-encrypted laptop and will not be shared outside the Ilamona team. It contains TLP-tagged intelligence — please flag if any records are TLP:RED so I can handle them appropriately.

---

## Questions

If any of the field names above do not match the internal schema, or if certain fields are stored differently in the database, please let me know and I can clarify what I am looking for from the API response perspective. I can provide example API responses showing exactly the shape of data I expect, which should make it straightforward to map to the underlying tables.

Thank you.

---

*Barry Cheevers*  
