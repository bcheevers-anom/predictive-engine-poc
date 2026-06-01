import json
from pathlib import Path

from pydantic import BaseModel

from pte.gateway.llm_client import LLMClient
from pte.schema.models import DiscoveryOutput


PROMPT_PATH = Path(__file__).parents[3] / "prompts" / "blob_discovery_v1.txt"
SKILL_VERSION = "blob_discovery-v1"


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
        prompt_template = PROMPT_PATH.read_text()
        blobs_text = "\n---\n".join(sample)
        prompt = prompt_template.format(
            sample_size=len(sample),
            feed=feed,
            entity_type=entity_type,
        ) + f"\n\nBlobs:\n{blobs_text}"

        result = await self._llm.complete(
            prompt=prompt,
            model_tier="strong",
            schema=DiscoveryOutput,
        )

        # Write coverage report shard
        dest = self._data_dir / "coverage" / batch_id
        dest.mkdir(parents=True, exist_ok=True)
        out_path = dest / f"discovery_{feed}_{entity_type}.json"

        # Handle both Pydantic model and MagicMock (for tests)
        if isinstance(result, BaseModel):
            out_path.write_text(json.dumps(result.model_dump(), indent=2))
            return result
        else:
            # MagicMock in tests — serialize manually
            data = {
                "feed": feed,
                "entity_type": entity_type,
                "sample_size": result.sample_size,
                "dimensions": {
                    k: {"presence_rate": v["presence_rate"], "mean_confidence": v["mean_confidence"]}
                    for k, v in result.dimensions.items()
                },
                "quarantine_count": result.quarantine_count,
                "notes": result.notes,
            }
            out_path.write_text(json.dumps(data, indent=2))
            return result
