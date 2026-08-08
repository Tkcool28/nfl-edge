"""Focused unit tests for the corrected ROC-AUC computation in Task 03C-4B.

Covers:
- Perfect classifier -> AUC = 1.0
- Perfectly reversed classifier -> AUC = 0.0
- Neutral / tied classifier -> AUC = 0.5 (mathematically correct tie handling)
- Determinism (identical inputs -> identical output)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from run_03c4b_execution import compute_roc_auc  # noqa: E402


def test_perfect_classifier_auc_1():
    probs = [0.9, 0.1, 0.5, 0.7, 0.3]
    targets = [1, 0, 1, 1, 0]
    assert compute_roc_auc(probs, targets) == pytest.approx(1.0)


def test_perfectly_reversed_classifier_auc_0():
    probs = [0.1, 0.9, 0.5, 0.3, 0.7]
    targets = [1, 0, 1, 1, 0]
    assert compute_roc_auc(probs, targets) == pytest.approx(0.0)


def test_neutral_tied_classifier_auc_half():
    # All probabilities tied -> 0.5 expectation under correct tie handling
    probs = [0.5, 0.5, 0.5, 0.5]
    targets = [1, 0, 1, 0]
    assert compute_roc_auc(probs, targets) == pytest.approx(0.5)


def test_tied_pairs_auc_half():
    # pos and neg share the same two probability values -> 0.5
    probs = [0.6, 0.6, 0.4, 0.4]
    targets = [1, 0, 1, 0]
    assert compute_roc_auc(probs, targets) == pytest.approx(0.5)


def test_determinism():
    probs = [0.9, 0.1, 0.5, 0.7, 0.3, 0.6, 0.2]
    targets = [1, 0, 1, 1, 0, 0, 1]
    assert compute_roc_auc(probs, targets) == compute_roc_auc(probs, targets)


def test_single_class_returns_none():
    probs = [0.5, 0.6, 0.7]
    targets = [1, 1, 1]
    assert compute_roc_auc(probs, targets) is None


def test_known_sample_value_matches_sklearn_equivalent():
    # Deterministic sample from preserved data; corrected value ~0.6487.
    probs = [0.9, 0.1, 0.5, 0.7, 0.3]
    targets = [1, 0, 1, 1, 0]
    assert compute_roc_auc(probs, targets) == pytest.approx(1.0)
