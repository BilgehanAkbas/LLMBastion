from ml.external_eval_deepset import ML_THRESHOLD


def test_external_eval_uses_fixed_calibrated_threshold():
    assert ML_THRESHOLD == 0.60
