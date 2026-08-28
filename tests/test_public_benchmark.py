from ml.public_benchmark_slabs import (
    THRESHOLDS,
    predictions_from_probabilities,
)


def test_public_benchmark_thresholds_are_ordered():
    assert THRESHOLDS == tuple(sorted(THRESHOLDS))


def test_probability_thresholding():
    probabilities = [0.20, 0.49, 0.50, 0.80]

    assert predictions_from_probabilities(
        probabilities,
        0.50,
    ) == [False, False, True, True]
