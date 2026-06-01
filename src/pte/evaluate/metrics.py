import numpy as np
from sklearn.metrics import average_precision_score


def pr_auc(y_true: list[int], y_scores: list[float]) -> float:
    if len(set(y_true)) < 2:
        return 0.0
    return float(average_precision_score(y_true, y_scores))


def top_k_accuracy(y_true: list[int], y_scores: list[float], k: int = 3) -> float:
    pairs = sorted(zip(y_scores, y_true), reverse=True)
    top_k = pairs[:k]
    return sum(y for _, y in top_k) / min(k, sum(y_true)) if sum(y_true) > 0 else 0.0


def calibration_ece(y_true: list[int], y_probs: list[float], n_bins: int = 10) -> float:
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    n = len(y_true)
    for i in range(n_bins):
        mask = [(bins[i] <= p < bins[i+1]) for p in y_probs]
        if not any(mask):
            continue
        bin_probs = [p for p, m in zip(y_probs, mask) if m]
        bin_true = [t for t, m in zip(y_true, mask) if m]
        ece += len(bin_probs) / n * abs(np.mean(bin_probs) - np.mean(bin_true))
    return float(ece)


def mae(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    return float(np.mean([abs(a - p) for a, p in zip(actual, predicted)]))
