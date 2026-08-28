from ml.train_and_compare import (
    TEST_PATH,
    TRAIN_PATH,
    build_model,
    load_jsonl,
    metrics_from_predictions,
)


def test_ml_threshold_changes_tradeoff():
    train_rows = load_jsonl(TRAIN_PATH)
    test_rows = load_jsonl(TEST_PATH)

    model = build_model()
    model.fit(
        [row["text"] for row in train_rows],
        [1 if row["label"] == "attack" else 0 for row in train_rows],
    )

    probabilities = model.predict_proba(
        [row["text"] for row in test_rows]
    )[:, 1]

    low_predictions = [p >= 0.50 for p in probabilities]
    high_predictions = [p >= 0.70 for p in probabilities]

    low_metrics = metrics_from_predictions(test_rows, low_predictions)
    high_metrics = metrics_from_predictions(test_rows, high_predictions)

    assert high_metrics.false_positive_rate <= low_metrics.false_positive_rate
    assert high_metrics.recall <= low_metrics.recall
