from abc import ABC, abstractmethod
from typing import Any


class Task(ABC):
    task_id: str = ""
    accepted_tiers: list[str] = []
    aql_port_idiom: str = ""
    metric: str = ""
    horizon: str = ""

    def __init__(self, batch_id: str, data_dir: str = "data"):
        self.batch_id = batch_id
        self.data_dir = data_dir

    @abstractmethod
    def fit(self) -> None: ...

    @abstractmethod
    def predict(self, inputs: Any) -> Any: ...

    @abstractmethod
    def explain(self, inputs: Any) -> dict: ...

    @abstractmethod
    def evaluate(self) -> dict: ...


def get_task(task_name: str, batch_id: str, data_dir: str = "data") -> Task:
    mapping = {
        "t1": "pte.predict.t1_vuln_exploit.T1VulnExploit",
        "t2": "pte.predict.t2_tool_tactic.T2ToolTactic",
        "t2-industry": "pte.predict.t2_industry.T2Industry",
        "t3": "pte.predict.t3_company.T3Company",
    }
    if task_name not in mapping:
        raise ValueError(f"Unknown task: {task_name}. Available: {list(mapping)}")
    module_path, class_name = mapping[task_name].rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(batch_id=batch_id, data_dir=data_dir)
