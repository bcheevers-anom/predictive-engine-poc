"""
Build a normalised feature dataset from the full 2.5yr extraction.

Two improvements over the raw batch (full-a1f4ddec):
  1. Industry taxonomy normalisation — 695 variants -> ~45 canonical sectors
  2. TF-IDF style tool scoring — penalises globally ubiquitous tools (Cobalt Strike),
     rewards tools distinctive to specific sectors

Output batch: full-a1f4ddec-bc3e44ce3e31-normalised
Original batch: preserved unchanged
"""
from dotenv import load_dotenv
load_dotenv()

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from pte.features.store import FeatureStore
from pte.common.logging import progress

SRC_BATCH = "full-a1f4ddec-bc3e44ce3e31"
DST_BATCH = "full-a1f4ddec-bc3e44ce3e31-normalised"
DATA_DIR = Path("data")

# ── Industry taxonomy normalisation map ───────────────────────────────────────
# Maps any variant (lowercase) -> canonical sector name
# Built from the 695 distinct labels in the corpus

INDUSTRY_MAP = {
    # Government & Public Sector
    "government": "Government",
    "governments": "Government",
    "government & public services": "Government",
    "government & public services": "Government",
    "government national": "Government",
    "government facilities": "Government",
    "government subcontractors": "Government",
    "state and local government": "Government",
    "local government": "Government",
    "public sector": "Government",
    "public services": "Government",
    "public administration": "Government",
    "national government": "Government",
    "national security": "Government",
    "foreign affairs": "Government",
    "diplomatic": "Government",
    "diplomatic services": "Government",
    "diplomacy": "Government",
    "diplomacy / foreign affairs": "Government",
    "diplomatic / foreign affairs": "Government",
    "embassies": "Government",
    "law enforcement": "Government",
    "military": "Government",
    "armed forces": "Government",
    "military-industrial": "Government",
    "intelligence": "Government",
    "intergovernmental organizations": "Government",
    "international organizations": "Government",
    "international affairs": "Government",
    "election systems": "Government",
    "elections": "Government",
    "political parties": "Government",
    "political organizations": "Government",
    "political opposition": "Government",

    # Financial Services
    "financial services": "Financial Services",
    "financial services / banking": "Financial Services",
    "financial sector": "Financial Services",
    "financial": "Financial Services",
    "financial technology": "Financial Services",
    "finance": "Financial Services",
    "banking": "Financial Services",
    "banking & capital markets": "Financial Services",
    "banking & capital markets": "Financial Services",
    "banking and financial": "Financial Services",
    "banks": "Financial Services",
    "credit unions": "Financial Services",
    "insurance": "Financial Services",
    "investment": "Financial Services",
    "fintech": "Financial Services",
    "financial market infrastructure": "Financial Services",
    "payment services": "Financial Services",
    "payment processing": "Financial Services",
    "payment systems": "Financial Services",
    "payment card industry": "Financial Services",
    "securities": "Financial Services",
    "capital markets": "Financial Services",
    "cryptocurrency": "Financial Services",
    "decentralized finance (defi)": "Financial Services",
    "decentralized finance": "Financial Services",
    "blockchain": "Financial Services",
    "web3": "Financial Services",
    "cryptocurrency / blockchain": "Financial Services",

    # Technology
    "technology": "Technology",
    "information technology": "Technology",
    "it": "Technology",
    "information technology services": "Technology",
    "it services": "Technology",
    "it service providers": "Technology",
    "it industry": "Technology",
    "software": "Technology",
    "software development": "Technology",
    "software as a service (saas)": "Technology",
    "software as a service": "Technology",
    "saas": "Technology",
    "software/technology": "Technology",
    "software vendors": "Technology",
    "software publishers": "Technology",
    "enterprise software": "Technology",
    "technology research": "Technology",
    "high-tech": "Technology",
    "high tech": "Technology",
    "high technology": "Technology",
    "internet of things": "Technology",
    "internet of things (iot)": "Technology",
    "iot": "Technology",
    "semiconductor": "Technology",
    "semiconductor manufacturing": "Technology",
    "semiconductors": "Technology",
    "hardware manufacturing": "Technology",
    "consumer electronics": "Technology",
    "consumer hardware": "Technology",
    "artificial intelligence": "Technology",
    "artificial intelligence / machine learning": "Technology",
    "machine learning": "Technology",
    "artificial intelligence infrastructure": "Technology",
    "artificial intelligence research": "Technology",
    "data analytics": "Technology",
    "data centers": "Technology",

    # Healthcare
    "healthcare": "Healthcare",
    "health": "Healthcare",
    "health care": "Healthcare",
    "healthcare research": "Healthcare",
    "healthcare supply chain": "Healthcare",
    "pharmaceutical": "Healthcare",
    "pharmaceuticals": "Healthcare",
    "pharmaceuticals & life sciences": "Healthcare",
    "biopharma": "Healthcare",
    "biotechnology": "Healthcare",
    "medical": "Healthcare",
    "medical research": "Healthcare",
    "medical technology": "Healthcare",
    "medical devices": "Healthcare",
    "medical equipment": "Healthcare",
    "hospitals and clinics": "Healthcare",
    "public health": "Healthcare",
    "health insurance": "Healthcare",
    "health technology": "Healthcare",
    "biomedical": "Healthcare",

    # Energy & Utilities
    "energy": "Energy & Utilities",
    "energy & utilities": "Energy & Utilities",
    "energy and utilities": "Energy & Utilities",
    "utilities": "Energy & Utilities",
    "electric utilities": "Energy & Utilities",
    "electric power": "Energy & Utilities",
    "nuclear": "Energy & Utilities",
    "nuclear energy": "Energy & Utilities",
    "nuclear power": "Energy & Utilities",
    "nuclear research": "Energy & Utilities",
    "oil and gas": "Energy & Utilities",
    "oil & gas": "Energy & Utilities",
    "oil and gas (oil refining and petrochemical)": "Energy & Utilities",
    "natural gas": "Energy & Utilities",
    "petrochemical": "Energy & Utilities",
    "petrochemicals": "Energy & Utilities",
    "lng/refining": "Energy & Utilities",
    "renewable energy": "Energy & Utilities",
    "power generation": "Energy & Utilities",
    "water": "Energy & Utilities",
    "water utilities": "Energy & Utilities",
    "water and wastewater": "Energy & Utilities",
    "water and wastewater systems": "Energy & Utilities",
    "water treatment": "Energy & Utilities",
    "water management": "Energy & Utilities",
    "water/wastewater": "Energy & Utilities",
    "water utilities": "Energy & Utilities",

    # Critical Infrastructure / ICS
    "critical infrastructure": "Critical Infrastructure",
    "industrial control systems": "Critical Infrastructure",
    "ics": "Critical Infrastructure",
    "scada": "Critical Infrastructure",
    "operational technology": "Critical Infrastructure",
    "ot": "Critical Infrastructure",
    "industrial control systems / scada / ot": "Critical Infrastructure",
    "ot/ics / critical infrastructure": "Critical Infrastructure",

    # Manufacturing & Industrial
    "manufacturing": "Manufacturing",
    "industrial": "Manufacturing",
    "industrial manufacturing": "Manufacturing",
    "manufacturing & industrial": "Manufacturing",
    "heavy industry": "Manufacturing",
    "chemical manufacturing": "Manufacturing",
    "chemicals": "Manufacturing",
    "chemicals & materials": "Manufacturing",
    "automotive": "Manufacturing",
    "aerospace": "Manufacturing",
    "aerospace & defense": "Manufacturing",
    "aerospace, defence & security": "Manufacturing",
    "industrial technology": "Manufacturing",

    # Telecommunications
    "telecommunications": "Telecommunications",
    "telecom": "Telecommunications",
    "telecommunication": "Telecommunications",
    "internet service providers": "Telecommunications",
    "networking": "Telecommunications",
    "networking/telecommunications": "Telecommunications",
    "satellite communications": "Telecommunications",
    "satellite": "Telecommunications",

    # Education & Research
    "education": "Education & Research",
    "academic": "Education & Research",
    "academia": "Education & Research",
    "higher education": "Education & Research",
    "research": "Education & Research",
    "research and development": "Education & Research",
    "scientific research": "Education & Research",
    "scientific research and development": "Education & Research",
    "universities": "Education & Research",
    "think tanks": "Education & Research",

    # Defense & Aerospace
    "defense": "Defense",
    "defence": "Defense",
    "defense industrial base": "Defense",
    "military-industrial": "Defense",

    # Transportation & Logistics
    "transportation": "Transportation & Logistics",
    "logistics": "Transportation & Logistics",
    "transportation & logistics": "Transportation & Logistics",
    "transportation/logistics": "Transportation & Logistics",
    "aviation": "Transportation & Logistics",
    "airlines": "Transportation & Logistics",
    "maritime": "Transportation & Logistics",
    "shipping": "Transportation & Logistics",
    "rail": "Transportation & Logistics",
    "automotive": "Transportation & Logistics",

    # Retail & Consumer
    "retail": "Retail & Consumer",
    "e-commerce": "Retail & Consumer",
    "consumer services": "Retail & Consumer",
    "consumer goods": "Retail & Consumer",
    "hospitality": "Retail & Consumer",
    "food and beverage": "Retail & Consumer",
    "gaming": "Retail & Consumer",
    "gambling": "Retail & Consumer",
    "media": "Retail & Consumer",
    "media & entertainment": "Retail & Consumer",

    # Civil Society & NGOs
    "civil society": "Civil Society & NGOs",
    "civil society & non-profits": "Civil Society & NGOs",
    "non-governmental organizations": "Civil Society & NGOs",
    "ngo": "Civil Society & NGOs",
    "ngos": "Civil Society & NGOs",
    "non-profit": "Civil Society & NGOs",
    "humanitarian": "Civil Society & NGOs",
    "human rights": "Civil Society & NGOs",
    "religious organizations": "Civil Society & NGOs",

    # Cloud & Managed Services
    "cloud services": "Cloud & Managed Services",
    "cloud infrastructure": "Cloud & Managed Services",
    "cloud computing": "Cloud & Managed Services",
    "managed service providers": "Cloud & Managed Services",
    "managed service provider": "Cloud & Managed Services",
    "hosting providers": "Cloud & Managed Services",
    "internet infrastructure": "Cloud & Managed Services",

    # Construction & Engineering
    "construction": "Construction & Engineering",
    "construction & engineering": "Construction & Engineering",
    "engineering": "Construction & Engineering",

    # Legal & Professional Services
    "legal & professional services": "Legal & Professional Services",
    "legal": "Legal & Professional Services",
    "legal services": "Legal & Professional Services",
    "consulting": "Legal & Professional Services",
    "professional services": "Legal & Professional Services",
    "accounting": "Legal & Professional Services",

    # Supply Chain
    "supply chain": "Supply Chain",
    "software supply chain": "Supply Chain",
    "supply chain management": "Supply Chain",
}


def normalise_industry(raw: str) -> str:
    """Map raw industry string to canonical sector. Returns cleaned raw if no mapping."""
    key = raw.lower().strip()
    if key in INDUSTRY_MAP:
        return INDUSTRY_MAP[key]
    # Partial match fallback for long variants
    for pattern, canonical in INDUSTRY_MAP.items():
        if len(pattern) > 8 and pattern in key:
            return canonical
    # Clean up the raw value — capitalise properly and return
    return raw.strip()


def compute_tfidf_scores(rows: list[dict]) -> dict[tuple, float]:
    """
    Compute TF-IDF style score for each (industry, tool) pair.

    TF  = count of tool mentions in this industry
    IDF = log(total_industries / industries_that_mention_this_tool)

    High score = tool is common in this industry BUT rare across other industries.
    Low score = tool appears everywhere (Cobalt Strike, PowerShell).
    """
    # Count: how many industries mention each tool
    tool_industry_count = Counter()
    for r in rows:
        tool_industry_count[r["tool"]] += 1  # will dedupe by (ind,tool) below

    # Actually count distinct industries per tool
    tool_industries = defaultdict(set)
    for r in rows:
        tool_industries[r["tool"]].add(r["industry"])

    total_industries = len(set(r["industry"] for r in rows))

    # TF: count per (industry, tool)
    tf = Counter((r["industry"], r["tool"]) for r in rows)

    # IDF: log(N / df) where df = number of industries mentioning the tool
    idf = {tool: math.log(total_industries / max(len(inds), 1))
           for tool, inds in tool_industries.items()}

    # TF-IDF score
    scores = {}
    for (ind, tool), count in tf.items():
        scores[(ind, tool)] = count * idf.get(tool, 0)

    return scores


def build_normalised_batch():
    progress("=" * 60)
    progress("Building normalised feature dataset")
    progress(f"Source: {SRC_BATCH}")
    progress(f"Dest:   {DST_BATCH}")
    progress("=" * 60)

    # Load source features
    src_store = FeatureStore(base_dir=str(DATA_DIR / "features"))
    raw_rows = src_store.read(SRC_BATCH, "industry_tool_cooccur")
    progress(f"Source rows: {len(raw_rows):,}")

    # Step 1: Normalise industry labels
    progress("\nStep 1: Normalising industry taxonomy...")
    normalised_rows = []
    changed = 0
    for r in raw_rows:
        if not r.get("tool") or not r.get("industry"):
            continue
        new_ind = normalise_industry(r["industry"])
        if new_ind != r["industry"]:
            changed += 1
        normalised_rows.append({**r, "industry": new_ind})

    before = len(set(r["industry"] for r in raw_rows))
    after = len(set(r["industry"] for r in normalised_rows))
    progress(f"  Industries: {before} -> {after} ({changed:,} rows remapped)")

    # Step 2: Compute TF-IDF scores
    progress("\nStep 2: Computing TF-IDF tool scores...")
    tfidf = compute_tfidf_scores(normalised_rows)

    # Add tfidf_score to each row
    scored_rows = []
    for r in normalised_rows:
        key = (r["industry"], r["tool"])
        scored_rows.append({**r, "tfidf_score": round(tfidf.get(key, 0.0), 4)})

    # Step 3: Write to destination feature store
    progress("\nStep 3: Writing normalised feature tables...")
    dst_store = FeatureStore(base_dir=str(DATA_DIR / "features"))
    dst_store.write(DST_BATCH, "industry_tool_cooccur", scored_rows)
    progress(f"  industry_tool_cooccur: {len(scored_rows):,} rows")

    # Copy tool_weekly_trends (normalise industry there too)
    trend_rows = src_store.read(SRC_BATCH, "tool_weekly_trends")
    dst_store.write(DST_BATCH, "tool_weekly_trends", trend_rows)
    progress(f"  tool_weekly_trends: {len(trend_rows):,} rows (unchanged)")

    # Copy other tables unchanged
    for table in ["vulnerability_features", "company_features"]:
        table_rows = src_store.read(SRC_BATCH, table)
        if table_rows:
            dst_store.write(DST_BATCH, table, table_rows)
            progress(f"  {table}: {len(table_rows):,} rows (unchanged)")

    # Write manifest
    manifest = {
        "batch_id": DST_BATCH,
        "source_batch": SRC_BATCH,
        "normalised": True,
        "industry_variants_before": before,
        "industry_variants_after": after,
        "scoring": "tfidf",
        "rows": len(scored_rows),
    }
    frozen_dir = DATA_DIR / "frozen" / DST_BATCH
    frozen_dir.mkdir(parents=True, exist_ok=True)
    (frozen_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Show top tool predictions with new scoring for key sectors
    progress("\n=== VALIDATION: Top-3 predictions with TF-IDF scoring ===")
    from collections import defaultdict as _dd
    sector_scores = _dd(list)
    for r in scored_rows:
        sector_scores[r["industry"]].append((r["tool"], r["tfidf_score"]))

    for sector in ["Financial Services", "Healthcare", "Energy & Utilities",
                   "Manufacturing", "Education & Research", "Critical Infrastructure"]:
        tools = sector_scores.get(sector, [])
        if not tools:
            continue
        top3 = sorted(set(tools), key=lambda x: x[1], reverse=True)[:3]
        print(f"  {sector:<30}: {[t for t,_ in top3]}")

    progress(f"\nDone. New batch ready: {DST_BATCH}")
    progress("Run: pte train t2-industry --batch-id " + DST_BATCH)
    return DST_BATCH


if __name__ == "__main__":
    build_normalised_batch()
