from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.guards.input.rule_guard import RuleGuard
from app.policies.input_policy import DEFAULT_BLOCK_THRESHOLD, InputPolicy, PolicyAction


DATASET_PATH = Path(__file__).with_name("prompt_injection_v1.jsonl")
CURRENT_THRESHOLD = DEFAULT_BLOCK_THRESHOLD
THRESHOLDS = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00)


@dataclass(frozen=True)
class Metrics:
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float
    accuracy: float
    false_positive_rate: float
    false_negative_rate: float


def safe_divide(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def calculate_metrics(tp: int, fp: int, tn: int, fn: int) -> Metrics:
    precision = safe_divide(tp, tp + fp)
    recall = safe_divide(tp, tp + fn)
    f1 = safe_divide(2 * precision * recall, precision + recall)
    accuracy = safe_divide(tp + tn, tp + fp + tn + fn)
    false_positive_rate = safe_divide(fp, fp + tn)
    false_negative_rate = safe_divide(fn, fn + tp)

    return Metrics(
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        accuracy=accuracy,
        false_positive_rate=false_positive_rate,
        false_negative_rate=false_negative_rate,
    )


def load_dataset(path: Path = DATASET_PATH) -> list[dict]:
    samples = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))
    return samples


def evaluate(samples: list[dict], threshold: float) -> tuple[Metrics, list[dict]]:
    guard = RuleGuard()
    policy = InputPolicy(block_threshold=threshold)

    tp = fp = tn = fn = 0
    rows = []

    for sample in samples:
        result = guard.analyze(sample["text"])
        decision = policy.decide(result.score)

        actual_attack = sample["label"] == "attack"
        predicted_attack = decision.action == PolicyAction.BLOCK

        if actual_attack and predicted_attack:
            tp += 1
            outcome = "TP"
        elif not actual_attack and predicted_attack:
            fp += 1
            outcome = "FP"
        elif not actual_attack and not predicted_attack:
            tn += 1
            outcome = "TN"
        else:
            fn += 1
            outcome = "FN"

        rows.append({
            **sample,
            "score": result.score,
            "action": decision.action.value,
            "matched_rules": list(result.matched_rules),
            "outcome": outcome,
        })

    return calculate_metrics(tp, fp, tn, fn), rows


def print_metrics(title: str, metrics: Metrics) -> None:
    print(title)
    print("-" * len(title))
    print(f"TP={metrics.tp}  FP={metrics.fp}  TN={metrics.tn}  FN={metrics.fn}")
    print(f"Precision: {metrics.precision:.3f}")
    print(f"Recall:    {metrics.recall:.3f}")
    print(f"F1:        {metrics.f1:.3f}")
    print(f"Accuracy:  {metrics.accuracy:.3f}")
    print(f"FPR:       {metrics.false_positive_rate:.3f}")
    print(f"FNR:       {metrics.false_negative_rate:.3f}")
    print()


def print_error_cases(rows: list[dict], outcome: str, limit: int = 12) -> None:
    cases = [row for row in rows if row["outcome"] == outcome]
    print(f"{outcome} examples ({len(cases)} total)")
    print("-" * 40)

    for row in cases[:limit]:
        print(
            f'{row["id"]} | score={row["score"]:.2f} | '
            f'rules={row["matched_rules"]} | {row["text"]}'
        )

    if len(cases) > limit:
        print(f"... {len(cases) - limit} more")
    print()


def main() -> None:
    samples = load_dataset()
    safe_count = sum(sample["label"] == "safe" for sample in samples)
    attack_count = sum(sample["label"] == "attack" for sample in samples)

    print(f"Dataset: {len(samples)} prompts ({safe_count} safe / {attack_count} attack)")
    print("Source: synthetic_v1 (hand-curated baseline evaluation set)")
    print()

    current_metrics, current_rows = evaluate(samples, CURRENT_THRESHOLD)
    print_metrics(
        f"Current baseline @ threshold={CURRENT_THRESHOLD:.2f}",
        current_metrics,
    )

    print("Threshold sweep")
    print("-" * 74)
    print("threshold  precision  recall   f1      accuracy  fpr     fnr")
    sweep = []

    for threshold in THRESHOLDS:
        metrics, _ = evaluate(samples, threshold)
        sweep.append((threshold, metrics))
        print(
            f"{threshold:>8.2f}  "
            f"{metrics.precision:>9.3f}  "
            f"{metrics.recall:>6.3f}  "
            f"{metrics.f1:>6.3f}  "
            f"{metrics.accuracy:>8.3f}  "
            f"{metrics.false_positive_rate:>6.3f}  "
            f"{metrics.false_negative_rate:>6.3f}"
        )

    best_threshold, best_metrics = max(
        sweep,
        key=lambda item: (item[1].f1, item[1].recall, -item[1].false_positive_rate),
    )

    print()
    print(
        "Best F1 on this synthetic dataset: "
        f"threshold={best_threshold:.2f}, F1={best_metrics.f1:.3f}, "
        f"recall={best_metrics.recall:.3f}, precision={best_metrics.precision:.3f}"
    )
    print(
        "Note: do not treat this as a production threshold. "
        "The dataset is synthetic and intentionally small."
    )
    print()

    fn_rows = [row for row in current_rows if row["outcome"] == "FN"]
    scoring_misses = [row for row in fn_rows if row["score"] > 0]
    coverage_misses = [row for row in fn_rows if row["score"] == 0]

    print("False-negative breakdown")
    print("-" * 40)
    print(f"Detected but below threshold: {len(scoring_misses)}")
    print(f"No RuleGuard match:           {len(coverage_misses)}")
    print()

    print_error_cases(current_rows, "FN")
    print_error_cases(current_rows, "FP")


if __name__ == "__main__":
    main()
