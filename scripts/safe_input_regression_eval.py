"""Evaluation-only SAFE fixtures; never trains or alters runtime policy."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests/fixtures/safe_gateway_regression.json"


def evaluate_cases(cases):
    from app.guards.input.rule_guard import RuleGuard
    from app.guards.input.semantic_guard import SemanticGuard
    from app.guards.input.benign_intent import adapt_semantic_signal
    from app.policies.input_policy import InputPolicy
    from app.services.risk_engine import RiskEngine

    rule, semantic, risk, policy = RuleGuard(), SemanticGuard(), RiskEngine(), InputPolicy()
    semantic.ensure_ready()
    rows = []
    for case in cases:
        started = time.perf_counter()
        rule_result = rule.analyze(case["prompt"])
        semantic_started = time.perf_counter()
        semantic_result = semantic.analyze(case["prompt"])
        semantic_latency = (time.perf_counter() - semantic_started) * 1000
        signal = adapt_semantic_signal(case["prompt"], rule_result, semantic_result.score, risk.semantic_threshold)
        assessment = risk.assess(rule_score=rule_result.score, semantic_score=signal.effective_score)
        action = policy.decide_assessment(assessment).action.value
        rows.append({"id": case["id"], "category": case["category"], "language": case["language"],
                     "expected_action": case.get("expected_action", "ALLOW"), "rule_score": rule_result.score,
                     "semantic_score": semantic_result.score,
                     "semantic_action": "BLOCK" if semantic_result.score >= risk.semantic_threshold else "ALLOW",
                     "effective_semantic_score": signal.effective_score, **signal.evidence,
                     "gateway_action": action, "triggered_detectors": assessment.triggered_detectors,
                     "semantic_latency_ms": round(semantic_latency, 3),
                     "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                     "passed": action == case.get("expected_action", "ALLOW")})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "reports/safe_input_regression.json")
    args = parser.parse_args()
    rows = evaluate_cases(json.loads(FIXTURES.read_text(encoding="utf-8")))
    report = {"evaluation_only": True, "semantic_threshold": 0.51, "training_performed": False,
              "summary": {"total": len(rows), "passed": sum(r["passed"] for r in rows),
                          "failures": [r["id"] for r in rows if not r["passed"]]}, "cases": rows}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"]))
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
