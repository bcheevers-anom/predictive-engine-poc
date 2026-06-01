import pytest
from pte.dedup.l1_observable import l1_dedup_batch, normalise_observable_key
from pte.dedup.merge import build_canonical_record
from pte.dedup.l2_entity import l2_entity_resolution

def test_l1_dedup_collapses_same_ip():
    records = [
        {"id": "r1", "value": "10.0.0.1", "itype": "ip", "source_feed": "threatfox"},
        {"id": "r2", "value": "10.0.0.1", "itype": "ip", "source_feed": "crowdstrike"},
    ]
    result = l1_dedup_batch(records)
    assert len(result) == 1
    assert result[0]["source_feed_count"] == 2
    assert result[0]["dedup_status"] == "merged"
    assert set(result[0]["merged_from"]) == {"r1", "r2"}

def test_l1_dedup_preserves_distinct():
    records = [
        {"id": "r1", "value": "10.0.0.1", "itype": "ip", "source_feed": "a"},
        {"id": "r2", "value": "10.0.0.2", "itype": "ip", "source_feed": "a"},
    ]
    result = l1_dedup_batch(records)
    assert len(result) == 2

def test_l1_normalise_key_case_insensitive():
    k1 = normalise_observable_key("DOMAIN.COM", "domain")
    k2 = normalise_observable_key("domain.com", "domain")
    assert k1 == k2


def test_l2_resolves_apt29_aliases():
    entities = [
        {"id": "actor-1", "entity_type": "actor", "name": "Cozy Bear", "source_feed": "gti"},
        {"id": "actor-2", "entity_type": "actor", "name": "APT29", "source_feed": "mandiant"},
        {"id": "actor-3", "entity_type": "actor", "name": "Midnight Blizzard", "source_feed": "crowdstrike"},
    ]
    result = l2_entity_resolution(entities)
    assert len(result) == 1
    assert result[0]["source_feed_count"] == 3
    assert set(result[0]["merged_from"]) == {"actor-1", "actor-2", "actor-3"}


def test_l2_unknown_alias_goes_to_unmapped():
    entities = [
        {"id": "actor-99", "entity_type": "actor", "name": "SomeTotallyUnknownActorXYZ", "source_feed": "osint"},
    ]
    result = l2_entity_resolution(entities)
    assert len(result) == 1
    assert result[0]["dedup_status"] == "singleton"
