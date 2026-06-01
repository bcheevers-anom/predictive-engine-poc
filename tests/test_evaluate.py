import pytest
import numpy as np
from pte.evaluate.metrics import pr_auc, top_k_accuracy, calibration_ece

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
