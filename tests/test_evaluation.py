import pytest

from evaluation.evaluate_rule_guard import (
    DATASET_PATH,
    calculate_metrics,
    load_dataset,
)


def test_evaluation_dataset_is_balanced():
    samples = load_dataset(DATASET_PATH)

    assert len(samples) == 100
    assert sum(sample["label"] == "safe" for sample in samples) == 50
    assert sum(sample["label"] == "attack" for sample in samples) == 50


def test_metrics_are_calculated_correctly():
    metrics = calculate_metrics(tp=8, fp=2, tn=18, fn=2)

    assert metrics.precision == 0.8
    assert metrics.recall == 0.8
    assert metrics.f1 == pytest.approx(0.8)
    assert metrics.accuracy == pytest.approx(26 / 30)
    assert metrics.false_positive_rate == 0.1
    assert metrics.false_negative_rate == 0.2
