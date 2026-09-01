import sklearn

from ml.build_semantic_guard_v2_artifact import (
    build_artifact_metadata,
)


def test_artifact_metadata_records_runtime_version():
    metadata = build_artifact_metadata(
        training_rows=840,
    )

    assert metadata["artifact_format"] == 1
    assert metadata["semantic_guard_version"] == "v2"
    assert (
        metadata["scikit_learn_version"]
        == sklearn.__version__
    )
    assert metadata["training_rows"] == 840
    assert (
        metadata["model_type"]
        == "word_tfidf_logistic_regression"
    )
