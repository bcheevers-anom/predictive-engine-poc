import json
from pathlib import Path

from pydantic import BaseModel, Field

from pte.gateway.llm_client import LLMClient
from pte.schema.models import DiscoveryOutput, DimensionStats


PROMPT_PATH = Path(__file__).parents[3] / "prompts" / "blob_discovery_v1.txt"
SKILL_VERSION = "blob_discovery-v1"


class _DiscoveryLLMOutput(BaseModel):
    """Schema the LLM fills in — metadata fields are set by code, not by the model."""
    dimensions: dict[str, DimensionStats]
    quarantine_count: int = 0
    notes: str = ""


class DiscoveryRunner:
    def __init__(self, llm_client: LLMClient, data_dir: str = "data", run_id: str = ""):
        self._llm = llm_client
        self._data_dir = Path(data_dir)
        self._run_id = run_id

    async def run_slice(
        self,
        batch_id: str,
        feed: str,
        entity_type: str,
        blobs: list[str],
        sample_size: int = 50,
    ) -> DiscoveryOutput:
        sample = blobs[:sample_size]
        # Truncate each blob to 1500 chars to keep total prompt within model context
        MAX_BLOB_CHARS = 1500
        truncated = [b[:MAX_BLOB_CHARS] for b in sample]
        prompt_template = PROMPT_PATH.read_text()
        blobs_text = "\n---\n".join(truncated)
        prompt = prompt_template.format(
            sample_size=len(sample),
            feed=feed,
            entity_type=entity_type,
        ) + f"\n\nBlobs:\n{blobs_text}"

        # Use a minimal schema — code stamps feed/entity_type/sample_size, LLM fills dimensions
        llm_result = await self._llm.complete(
            prompt=prompt,
            model_tier="strong",
            schema=_DiscoveryLLMOutput,
        )

        # Stamp metadata
        if isinstance(llm_result, BaseModel):
            result = DiscoveryOutput(
                feed=feed,
                entity_type=entity_type,
                sample_size=len(sample),
                dimensions=llm_result.dimensions,
                quarantine_count=llm_result.quarantine_count,
                notes=llm_result.notes,
            )
        else:
            # MagicMock in tests
            result = DiscoveryOutput(
                feed=feed,
                entity_type=entity_type,
                sample_size=llm_result.sample_size,
                dimensions=llm_result.dimensions,
                quarantine_count=llm_result.quarantine_count,
                notes=llm_result.notes,
            )

        dest = self._data_dir / "coverage" / batch_id
        dest.mkdir(parents=True, exist_ok=True)
        out_path = dest / f"discovery_{feed}_{entity_type}.json"
        out_path.write_text(json.dumps(result.model_dump(), indent=2))
        return result
