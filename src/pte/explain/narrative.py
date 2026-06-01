import json
from pathlib import Path

PROMPT_PATH = Path(__file__).parents[3] / "prompts" / "narrative_v1.txt"


class NarrativeGenerator:
    def __init__(self, llm_client):
        self._llm = llm_client

    async def generate(self, finding: dict, max_retries: int = 1) -> dict:
        prompt_template = PROMPT_PATH.read_text()
        prompt = prompt_template.replace("{finding_json}", json.dumps(finding, indent=2))

        for attempt in range(max_retries + 1):
            result = await self._llm.complete(
                prompt=prompt,
                model_tier="mid",
            )
            faithfulness = getattr(result, "faithfulness_checked", False)
            if faithfulness:
                return {
                    "narrative": getattr(result, "narrative", ""),
                    "faithfulness_checked": True,
                    "rejected_claims": [],
                }
            if attempt == max_retries:
                return {
                    "narrative": getattr(result, "narrative", ""),
                    "faithfulness_checked": False,
                    "rejected_claims": getattr(result, "rejected_claims", []),
                }

        return {"narrative": "", "faithfulness_checked": False, "rejected_claims": []}
