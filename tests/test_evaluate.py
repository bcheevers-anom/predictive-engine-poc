import pytest
import numpy as np
from pte.evaluate.metrics import pr_auc, top_k_accuracy, calibration_ece, precision_at_k, recall_at_k, f1_at_k, mean_average_precision, ndcg_at_k

def test_pr_auc_perfect():
    y_true = [0, 0, 1, 1]
    y_scores = [0.1, 0.2, 0.8, 0.9]
    assert pr_auc(y_true, y_scores) > 0.9

def test_top_k_accuracy():
    y_true = [0, 0, 1, 0, 1]
    y_scores = [0.1, 0.2, 0.9, 0.3, 0.8]
    assert top_k_accuracy(y_true, y_scores, k=2) == 1.0

def test_calibration_ece_near_zero_for_perfect():
    y_true = [1, 0, 1, 0]
    y_probs = [0.95, 0.05, 0.90, 0.10]
    ece = calibration_ece(y_true, y_probs)
    assert ece < 0.2

def test_precision_at_k_perfect():
    assert precision_at_k(predicted=["A","B","C"], actual={"A","B","C"}) == 1.0

def test_precision_at_k_none():
    assert precision_at_k(predicted=["X","Y","Z"], actual={"A","B","C"}) == 0.0

def test_precision_at_k_partial():
    assert abs(precision_at_k(predicted=["A","X","Y"], actual={"A","B","C"}) - 1/3) < 0.001

def test_recall_at_k_perfect():
    assert recall_at_k(predicted=["A","B","C"], actual={"A","B"}) == 1.0

def test_recall_at_k_empty_actual():
    assert recall_at_k(predicted=["A"], actual=set()) == 0.0

def test_f1_at_k_perfect():
    assert f1_at_k(predicted=["A","B","C"], actual={"A","B","C"}) == 1.0

def test_f1_at_k_zero():
    assert f1_at_k(predicted=["X","Y","Z"], actual={"A","B","C"}) == 0.0

def test_mean_average_precision_perfect():
    results = [
        {"predicted": ["A","B","C"], "actual": {"A","B","C"}},
        {"predicted": ["X","Y","Z"], "actual": {"X","Y","Z"}},
    ]
    assert mean_average_precision(results) == 1.0

def test_mean_average_precision_empty():
    assert mean_average_precision([]) == 0.0

def test_ndcg_at_k_perfect():
    predicted = ["A", "B", "C"]
    actual_counts = {"A": 10, "B": 5, "C": 2}
    score = ndcg_at_k(predicted=predicted, actual_counts=actual_counts)
    assert abs(score - 1.0) < 0.001

def test_ndcg_at_k_zero():
    predicted = ["X", "Y", "Z"]
    actual_counts = {"A": 10, "B": 5, "C": 2}
    score = ndcg_at_k(predicted=predicted, actual_counts=actual_counts)
    assert score == 0.0
