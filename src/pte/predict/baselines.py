class EpssBaseline:
    def rank(self, data: list[dict], epss_field: str = "epss_score") -> list[dict]:
        return sorted(data, key=lambda r: r.get(epss_field, 0.0), reverse=True)

class FrequencyBaseline:
    def __init__(self, field: str = "count"):
        self._field = field

    def rank(self, data: list[dict]) -> list[dict]:
        return sorted(data, key=lambda r: r.get(self._field, 0), reverse=True)

class PreviousPeriodBaseline:
    def predict(self, current: list[float]) -> list[float]:
        return list(current)
