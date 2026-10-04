"""Desired SAFE behavior: known v2 false positives remain real test failures."""
import json

import pytest

from scripts.safe_input_regression_eval import FIXTURES, evaluate_cases

CASES = json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def assessments():
    return {row["id"]: row for row in evaluate_cases(CASES)}


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_safe_input_is_allowed(case, assessments):
    row = assessments[case["id"]]
    assert row["gateway_action"] == "ALLOW", (
        f"{case['id']}: rule={row['rule_score']}, semantic={row['semantic_score']}, "
        f"detectors={row['triggered_detectors']}"
    )
