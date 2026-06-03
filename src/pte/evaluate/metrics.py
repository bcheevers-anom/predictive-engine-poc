import math
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


def precision_at_k(predicted: list[str], actual: set[str]) -> float:
    """Fraction of predicted tools that actually appeared in the holdout."""
    if not predicted:
        return 0.0
    return sum(1 for t in predicted if t in actual) / len(predicted)


def recall_at_k(predicted: list[str], actual: set[str]) -> float:
    """Fraction of actual holdout tools that were predicted."""
    if not actual:
        return 0.0
    return sum(1 for t in predicted if t in actual) / len(actual)


def f1_at_k(predicted: list[str], actual: set[str]) -> float:
    """Harmonic mean of precision@k and recall@k."""
    p = precision_at_k(predicted, actual)
    r = recall_at_k(predicted, actual)
    return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def mean_average_precision(results: list[dict]) -> float:
    """Mean Average Precision across sectors.

    Each result dict must have keys:
      'predicted': list[str]  — ranked tool list
      'actual':    set[str]   — tools that appeared in holdout
    """
    if not results:
        return 0.0
    ap_scores = []
    for r in results:
        predicted = r.get("predicted", [])
        actual = r.get("actual", set())
        if not actual:
            continue
        hits = 0
        precision_sum = 0.0
        for i, tool in enumerate(predicted, 1):
            if tool in actual:
                hits += 1
                precision_sum += hits / i
        ap_scores.append(precision_sum / len(actual) if actual else 0.0)
    return float(np.mean(ap_scores)) if ap_scores else 0.0


def ndcg_at_k(predicted: list[str], actual_counts: dict[str, int]) -> float:
    """Normalised Discounted Cumulative Gain.

    Uses actual tool counts as relevance weights.
    predicted: ranked list of predicted tools
    actual_counts: dict mapping tool -> count in holdout
    """
    if not predicted or not actual_counts:
        return 0.0

    def dcg(ranking: list[str]) -> float:
        return sum(
            actual_counts.get(tool, 0) / math.log2(i + 2)
            for i, tool in enumerate(ranking)
        )

    ideal = sorted(actual_counts, key=actual_counts.get, reverse=True)[:len(predicted)]
    idcg = dcg(ideal)
    return dcg(predicted) / idcg if idcg > 0 else 0.0
