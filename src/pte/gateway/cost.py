import threading
from pathlib import Path
import yaml

def _load_pricing() -> dict:
    pricing_path = Path(__file__).parents[3] / "config" / "pricing.yaml"
    with open(pricing_path) as f:
        return yaml.safe_load(f)

class CostTracker:
    def __init__(self, backend: str, model_id: str):
        self.backend = backend
        self.model_id = model_id
        self._input_tokens = 0
        self._output_tokens = 0
        self._lock = threading.Lock()
        self._pricing = _load_pricing()

    def record(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens

    def summary(self) -> dict:
        try:
            rates = self._pricing[self.backend][self.model_id]
            cost = (
                self._input_tokens / 1_000_000 * rates["input_per_1m"]
                + self._output_tokens / 1_000_000 * rates["output_per_1m"]
            )
        except KeyError:
            cost = 0.0
        return {
            "backend": self.backend,
            "model_id": self.model_id,
            "total_input_tokens": self._input_tokens,
            "total_output_tokens": self._output_tokens,
            "estimated_cost_usd": round(cost, 4),
        }
