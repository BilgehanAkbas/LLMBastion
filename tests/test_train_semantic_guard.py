from ml.train_semantic_guard import MODEL_PATH, META_PATH


def test_semantic_artifact_paths_are_local():
    assert MODEL_PATH.name == "semantic_guard.joblib"
    assert META_PATH.name == "semantic_guard_meta.json"
