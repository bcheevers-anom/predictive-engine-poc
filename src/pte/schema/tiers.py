from enum import Enum

class DataTier(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    LLM_EXTRACTED = "LLM_EXTRACTED"
    EXTERNAL = "EXTERNAL"
    UNVALIDATED = "UNVALIDATED"

class TierPolicy:
    def __init__(self, accepted_tiers: list[str]):
        self._accepted = {DataTier(t) for t in accepted_tiers}

    def accepts(self, tier: DataTier) -> bool:
        return tier in self._accepted
