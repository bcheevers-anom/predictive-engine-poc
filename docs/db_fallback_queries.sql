-- =============================================================================
-- PTE Database Fallback Queries
-- =============================================================================
-- Use these if the ThreatStream REST API is unavailable.
-- Target: ThreatStream internal PostgreSQL database (Anomali Cloud deployment)
-- Org: Ilamona (org_id = 2956)
-- Date window: adjust the :from_date / :to_date parameters throughout
--
-- These queries reproduce what the PTE ingest pipeline fetches via REST:
--   1. Observable/IOC records   (replaces GET /api/v2/intelligence/)
--   2. Campaign entities        (replaces GET /api/v1/campaign/)
--   3. Actor entities           (replaces GET /api/v1/actor/)
--   4. Malware entities         (replaces GET /api/v1/malware/)
--   5. Vulnerability entities   (replaces GET /api/v1/vulnerability/)
--   6. Attack pattern entities  (replaces GET /api/v1/attackpattern/)
--   7. Sizing counts            (replaces GET ...?full_count=1)
--   8. Tag normalisation view   (reproduces normalize_tags.py)
--
-- Run order: sizing first (query 7), then entities, then observables.
-- Output: copy each result to a JSON/CSV file; place in data/raw/<batch_id>/
--
-- NOTE: Table and column names below are best-guess from the observed API
-- response shapes and standard Django ORM conventions Anomali uses.
-- A DBA may need to adjust names. The comments on each column reference
-- the API field name so mismatches are easy to spot.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 0. Parameters — set once, referenced throughout
-- ---------------------------------------------------------------------------
-- Replace these values before running:
--   :from_date  e.g. '2026-05-01'
--   :to_date    e.g. '2026-06-01'
--   :org_id     2956

-- In psql:
--   \set from_date '2026-05-01'
--   \set to_date   '2026-06-01'
--   \set org_id    2956


-- ===========================================================================
-- 1. OBSERVABLE / IOC RECORDS
--    API equivalent: GET /api/v2/intelligence/?created_ts__gte=:from&created_ts__lte=:to
--    Fields match the PTEEntity observable schema.
-- ===========================================================================
\echo '=== 1. Observables ==='

SELECT
    i.id,                                -- id
    i.uuid,                              -- uuid
    i.value,                             -- value (the indicator itself)
    i.type        AS type,               -- coarse type: domain/email/ip/md5/url/string
    i.itype,                             -- fine indicator type: mal_domain, c2_ip, phish_url …
    i.confidence,                        -- blended confidence 0-100
    i.source_reported_confidence,        -- source-provided confidence
    i.severity,                          -- low/medium/high/very-high
    i.status,                            -- active/inactive/falsepos
    i.threat_type,                       -- malware/c2/apt/compromised …
    i.tlp,
    i.source,                            -- feed name
    i.feed_id,
    i.retina_confidence,                 -- ML score; -1 = unscored (feed-dependent)
    i.country,                           -- IP geo
    i.asn,
    i.org         AS network_org,        -- registered owner/ISP
    i.latitude,
    i.longitude,
    i.created_ts,
    i.modified_ts,
    i.expiration_ts,
    i.source_created,
    i.source_modified,
    i.update_id,
    i.meta_detail   AS detail,           -- meta.detail
    i.meta_detail2  AS detail2,          -- meta.detail2 — lifecycle events, deactivation timestamps
    i.description,
    i.owner_organization_id,
    -- Tags as JSON array (join separately if needed — see query below)
    array_to_json(
        ARRAY(
            SELECT t.name
            FROM   intelligence_tag it
            JOIN   tag t ON t.id = it.tag_id
            WHERE  it.intelligence_id = i.id
        )
    ) AS tags
FROM   intelligence i
WHERE  i.owner_organization_id = :org_id
  AND  i.status != 'falsepos'                  -- exclude known false positives
  AND  i.created_ts >= :from_date::timestamptz
  AND  i.created_ts <  :to_date::timestamptz
ORDER BY i.created_ts DESC;


-- ===========================================================================
-- 2. CAMPAIGN ENTITIES
--    API equivalent: GET /api/v1/campaign/?created_ts__gte=:from&created_ts__lte=:to
-- ===========================================================================
\echo '=== 2. Campaigns ==='

SELECT
    c.id,
    c.uuid,
    'campaign'          AS model_type,
    c.name,
    c.status,
    c.tlp,
    c.feed_id,
    c.objective,
    c.status_desc,
    c.description,                       -- HTML body — primary LLM extraction target
    c.created_ts,
    c.modified_ts,
    c.published_ts,
    c.publication_status,
    c.source_created,
    c.source_modified,
    c.start_date,
    c.end_date,
    c.owner_organization_id,
    -- target_industry as JSON array
    array_to_json(
        ARRAY(
            SELECT ind.name
            FROM   campaign_target_industry cti
            JOIN   industry ind ON ind.id = cti.industry_id
            WHERE  cti.campaign_id = c.id
        )
    ) AS target_industry,
    -- tags_v2 as JSON array of {id, name, org_id}
    array_to_json(
        ARRAY(
            SELECT json_build_object('id', t.id, 'name', t.name, 'org_id', t.org_id)
            FROM   campaign_tag ct
            JOIN   tag t ON t.id = ct.tag_id
            WHERE  ct.campaign_id = c.id
        )
    ) AS tags_v2
FROM   campaign c
WHERE  c.owner_organization_id = :org_id
  AND  c.created_ts >= :from_date::timestamptz
  AND  c.created_ts <  :to_date::timestamptz
ORDER BY c.created_ts DESC;


-- ===========================================================================
-- 3. ACTOR ENTITIES
--    API equivalent: GET /api/v1/actor/?created_ts__gte=:from&created_ts__lte=:to
-- ===========================================================================
\echo '=== 3. Actors ==='

SELECT
    a.id,
    a.uuid,
    'actor'             AS model_type,
    a.name,
    a.status,
    a.tlp,
    a.feed_id,
    a.primary_motivation,
    a.resource_level,
    a.is_mitre,
    a.sophistication_type   AS soph_type,
    a.sophistication_desc   AS soph_desc,
    a.description,                       -- HTML body with STIX-ID relationship graph
    a.created_ts,
    a.modified_ts,
    a.published_ts,
    a.source_created,
    a.source_modified,
    a.owner_organization_id,
    -- aliases as JSON array of {id, resource_uri, name}
    array_to_json(
        ARRAY(
            SELECT json_build_object('id', al.id, 'name', al.name)
            FROM   actor_alias aa
            JOIN   actor al ON al.id = aa.alias_id
            WHERE  aa.actor_id = a.id
        )
    ) AS aliases,
    -- target_industry
    array_to_json(
        ARRAY(
            SELECT ind.name
            FROM   actor_target_industry ati
            JOIN   industry ind ON ind.id = ati.industry_id
            WHERE  ati.actor_id = a.id
        )
    ) AS target_industry,
    -- tags_v2
    array_to_json(
        ARRAY(
            SELECT json_build_object('id', t.id, 'name', t.name, 'org_id', t.org_id)
            FROM   actor_tag att
            JOIN   tag t ON t.id = att.tag_id
            WHERE  att.actor_id = a.id
        )
    ) AS tags_v2
FROM   actor a
WHERE  a.owner_organization_id = :org_id
  AND  a.created_ts >= :from_date::timestamptz
  AND  a.created_ts <  :to_date::timestamptz
ORDER BY a.created_ts DESC;


-- ===========================================================================
-- 4. MALWARE ENTITIES
--    API equivalent: GET /api/v1/malware/?created_ts__gte=:from&created_ts__lte=:to
-- ===========================================================================
\echo '=== 4. Malware ==='

SELECT
    m.id,
    m.uuid,
    'malware'           AS model_type,
    m.name,
    m.status,
    m.tlp,
    m.feed_id,
    m.is_family,
    m.description,                       -- HTML body (largely duplicates JSON for malware)
    m.created_ts,
    m.modified_ts,
    m.source_created,
    m.source_modified,
    m.owner_organization_id,
    -- capabilities (~75 normalised behavior tokens) — cleanest behavioral feature set
    array_to_json(
        ARRAY(
            SELECT mc.capability
            FROM   malware_capability mc
            WHERE  mc.malware_id = m.id
        )
    ) AS capabilities,
    -- malware_types
    array_to_json(
        ARRAY(
            SELECT mt.type_name
            FROM   malware_type mt
            WHERE  mt.malware_id = m.id
        )
    ) AS malware_types,
    -- execution_platforms
    array_to_json(
        ARRAY(
            SELECT mp.platform
            FROM   malware_platform mp
            WHERE  mp.malware_id = m.id
        )
    ) AS execution_platforms,
    -- aliases (flat strings for malware, unlike actor aliases)
    array_to_json(
        ARRAY(
            SELECT ma.alias
            FROM   malware_alias ma
            WHERE  ma.malware_id = m.id
        )
    ) AS aliases,
    -- tags_v2
    array_to_json(
        ARRAY(
            SELECT json_build_object('id', t.id, 'name', t.name, 'org_id', t.org_id)
            FROM   malware_tag mtt
            JOIN   tag t ON t.id = mtt.tag_id
            WHERE  mtt.malware_id = m.id
        )
    ) AS tags_v2
FROM   malware m
WHERE  m.owner_organization_id = :org_id
  AND  m.created_ts >= :from_date::timestamptz
  AND  m.created_ts <  :to_date::timestamptz
ORDER BY m.created_ts DESC;


-- ===========================================================================
-- 5. VULNERABILITY ENTITIES
--    API equivalent: GET /api/v1/vulnerability/?created_ts__gte=:from&created_ts__lte=:to
--    Clean numeric features: CVSS v2/v3, EPSS score/percentile.
-- ===========================================================================
\echo '=== 5. Vulnerabilities ==='

SELECT
    v.id,
    v.uuid,
    'vulnerability'     AS model_type,
    v.name,
    v.status,
    v.tlp,
    v.feed_id,
    v.cvss2_score,
    v.cvss3_score,
    v.epss_score,
    v.epss_percentile,
    v.description,
    v.created_ts,
    v.modified_ts,
    v.source_created,
    v.source_modified,
    v.owner_organization_id,
    -- exploitation tags (observable from live API)
    array_to_json(
        ARRAY(
            SELECT t.name
            FROM   vulnerability_tag vt
            JOIN   tag t ON t.id = vt.tag_id
            WHERE  vt.vulnerability_id = v.id
              AND  t.name IN (
                  'exploitation-state',
                  'observed-in-the-wild',
                  'was-zero-day',
                  'is-predicted',
                  'risk-rating'
              )
        )
    ) AS exploitation_tags,
    -- all tags_v2
    array_to_json(
        ARRAY(
            SELECT json_build_object('id', t.id, 'name', t.name, 'org_id', t.org_id)
            FROM   vulnerability_tag vt
            JOIN   tag t ON t.id = vt.tag_id
            WHERE  vt.vulnerability_id = v.id
        )
    ) AS tags_v2
FROM   vulnerability v
WHERE  v.owner_organization_id = :org_id
  AND  v.created_ts >= :from_date::timestamptz
  AND  v.created_ts <  :to_date::timestamptz
ORDER BY v.epss_score DESC NULLS LAST;


-- ===========================================================================
-- 6. ATTACK PATTERN ENTITIES (MITRE ATT&CK techniques)
--    API equivalent: GET /api/v1/attackpattern/
--    These are relatively static; date filter is optional.
-- ===========================================================================
\echo '=== 6. Attack patterns (MITRE) ==='

SELECT
    ap.id,
    ap.uuid,
    'attackpattern'     AS model_type,
    ap.name,                             -- e.g. "T1566.001 Spearphishing Attachment"
    ap.is_mitre,
    ap.status,
    ap.feed_id,
    ap.description,
    ap.created_ts,
    ap.modified_ts,
    ap.owner_organization_id
FROM   attackpattern ap
WHERE  ap.owner_organization_id = :org_id
  AND  ap.is_mitre = true
ORDER BY ap.name;


-- ===========================================================================
-- 7. SIZING CALIBRATION
--    Replicates the get_full_count() calls in frozen_batch.py.
--    Run this first to understand corpus scale before pulling full data.
-- ===========================================================================
\echo '=== 7. Sizing calibration ==='

SELECT
    'observable'    AS entity_type,
    COUNT(*)        AS total_count
FROM   intelligence
WHERE  owner_organization_id = :org_id
  AND  status != 'falsepos'
  AND  created_ts >= :from_date::timestamptz
  AND  created_ts <  :to_date::timestamptz

UNION ALL

SELECT 'campaign',   COUNT(*) FROM campaign     WHERE owner_organization_id = :org_id AND created_ts >= :from_date::timestamptz AND created_ts < :to_date::timestamptz
UNION ALL
SELECT 'actor',      COUNT(*) FROM actor        WHERE owner_organization_id = :org_id AND created_ts >= :from_date::timestamptz AND created_ts < :to_date::timestamptz
UNION ALL
SELECT 'malware',    COUNT(*) FROM malware      WHERE owner_organization_id = :org_id AND created_ts >= :from_date::timestamptz AND created_ts < :to_date::timestamptz
UNION ALL
SELECT 'vulnerability', COUNT(*) FROM vulnerability WHERE owner_organization_id = :org_id AND created_ts >= :from_date::timestamptz AND created_ts < :to_date::timestamptz
UNION ALL
SELECT 'attackpattern', COUNT(*) FROM attackpattern WHERE owner_organization_id = :org_id AND is_mitre = true

ORDER BY entity_type;


-- ===========================================================================
-- 8. TAG NORMALISATION VIEW
--    Reproduces what normalize_tags.py does — extract distinct non-workflow
--    tags from the observable corpus so the alias map can be extended.
--    Workflow tags start with 'Ilamona_' or 'PIR' — exclude them.
-- ===========================================================================
\echo '=== 8. Distinct tags (non-workflow) ==='

SELECT
    t.name,
    COUNT(*)            AS usage_count,
    COUNT(DISTINCT i.feed_id) AS feed_count
FROM   intelligence i
JOIN   intelligence_tag it ON it.intelligence_id = i.id
JOIN   tag t              ON t.id = it.tag_id
WHERE  i.owner_organization_id = :org_id
  AND  i.created_ts >= :from_date::timestamptz
  AND  i.created_ts <  :to_date::timestamptz
  AND  t.name NOT LIKE 'Ilamona_%'
  AND  t.name NOT LIKE 'PIR%'
  AND  t.name NOT LIKE 'pir%'
  AND  t.name NOT LIKE 'ilamona_%'
GROUP BY t.name
HAVING COUNT(*) >= 5           -- drop singletons
ORDER BY usage_count DESC
LIMIT 500;


-- ===========================================================================
-- HOW TO USE THIS FILE
-- ===========================================================================
--
-- Option A — psql interactive:
--   psql -h <host> -U <user> -d threatstream \
--     -v from_date='2026-05-01' -v to_date='2026-06-01' -v org_id=2956 \
--     -f docs/db_fallback_queries.sql \
--     -o data/raw/db_export.txt
--
-- Option B — export each query to a JSON file for the PTE pipeline:
--   psql ... -c "COPY (<query 1>) TO STDOUT (FORMAT csv, HEADER)" \
--     > data/raw/<batch_id>/observables.csv
--
--   Then load with:
--     import pandas as pd
--     df = pd.read_csv("data/raw/<batch_id>/observables.csv")
--     records = df.to_dict("records")
--     # Pass to l1_dedup_batch() and RawStore.write_bulk() as normal
--
-- Option C — JSON directly (PostgreSQL 9.5+):
--   psql ... -c "\copy (SELECT row_to_json(t) FROM (...query...) t) TO 'observables.jsonl'"
--
-- The batch_id for a DB-sourced ingest can be set manually:
--   batch_id = f"db-{from_date}-{to_date}"
--
-- ===========================================================================
