from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field

class ProvenanceRecord(BaseModel):
    run_id: str
    tier: str
    skill_version: str = ""
    endpoint: str = ""
    config_hash: str = ""

class SRO(BaseModel):
    relationship_type: str
    source_ref: str
    target_ref: str
    attribution_scope: str = ""
    extraction_confidence: float | None = None
    provenance: ProvenanceRecord | None = None

class PTEEntity(BaseModel):
    entity_id: str
    stix_id: str | None = None
    entity_type: str
    source_feed: str
    source_confidence: int | None = None
    observed_ts: str | None = None
    created_ts: str | None = None
    modified_ts: str | None = None
    first_seen: str | None = None
    last_seen: str | None = None
    actor: str | None = None
    campaign: str | None = None
    malware: str | None = None
    tool: str | None = None
    tactic: str | None = None
    technique: str | None = None
    observable: dict | None = None
    indicator_type: str | None = None
    industry: list[str] | None = None
    company: list[dict] | None = None
    geography: dict | None = None
    severity: str | None = None
    confidence: int | None = None
    tags: list[str] = Field(default_factory=list)
    relationships: list[SRO] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    provenance: ProvenanceRecord | None = None
    llm_extraction_confidence: float | None = None
    validation_status: str = "ok"
    features: dict | None = None
    # Dedup fields
    canonical_id: str | None = None
    merged_from: list[str] = Field(default_factory=list)
    source_feed_count: int = 1
    corroboration_score: float = 0.0
    distinct_event_count: int = 1
    dedup_confidence: float | None = None
    dedup_status: str = "singleton"

class Finding(BaseModel):
    # OCSF Detection Finding shape
    category_name: str = "Findings"
    class_name: str = "Detection Finding"
    title: str
    type_name: str
    severity: str
    confidence: float
    time_window: dict
    run_id: str
    prediction: dict | None = None
    evidence: list[dict] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    coverage: dict | None = None
    missing_data: list[str] = Field(default_factory=list)
    reliability_basis: str = ""
    calibration: dict | None = None
    baselines: dict | None = None
    metric: dict | None = None
    monitor_next: str = ""
    aql_port_idiom: str = ""
    viz_type: str = ""
    provenance: ProvenanceRecord | None = None

# Add DiscoveryOutput here too (needed by later tasks)
class DimensionStats(BaseModel):
    presence_rate: float
    mean_confidence: float

class DiscoveryOutput(BaseModel):
    feed: str
    entity_type: str
    sample_size: int
    dimensions: dict[str, DimensionStats]
    quarantine_count: int
    notes: str = ""
