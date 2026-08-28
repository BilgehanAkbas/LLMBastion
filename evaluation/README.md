# RuleGuard Evaluation v1

This folder measures the current regex-based RuleGuard baseline before adding a semantic or ML detector.

## Why this exists

A detector is not useful just because a few manual examples work. We need to know:

- how many attacks it catches,
- how many attacks it misses,
- how often it blocks harmless prompts,
- how the policy threshold changes that trade-off.

The first dataset is intentionally small and synthetic. It is a **baseline engineering dataset**, not a production benchmark.

## Dataset

`prompt_injection_v1.jsonl`

- 100 total prompts
- 50 safe
- 50 attack
- Turkish + English
- easy explicit attacks
- paraphrased attacks
- simple obfuscations
- benign security discussions and quoted attack phrases

The hard safe examples are important because a regex detector can mistake a harmless discussion *about* prompt injection for an actual attack.

## Run

From the project root:

```powershell
python evaluation/evaluate_rule_guard.py
```

This does **not** call Groq and does not need an API key.

## Metrics

- **Precision:** Of everything we blocked, how much was really an attack?
- **Recall:** Of all real attacks, how much did we catch?
- **F1:** Balance between precision and recall.
- **FPR:** How often harmless prompts are incorrectly blocked.
- **FNR:** How often attacks are incorrectly allowed.

## Important limitation

Do not optimize RuleGuard specifically to memorize this dataset. After the baseline analysis, the next dataset versions should include external/public examples and a held-out test split.


## Scoring v2

The first baseline exposed two separate problems:

1. Some attacks matched a rule but stayed below the old `0.70` policy threshold.
2. Some paraphrased/obfuscated attacks produced no rule match at all.

For v2, the policy threshold is calibrated to `0.50`, which allows a single explicit rule hit to block. To avoid blindly blocking harmless security discussions, RuleGuard applies a confidence reduction when the suspicious phrase is clearly quoted or used in generic meta-discussion context.

This is still a rule-based baseline. The remaining zero-match false negatives represent the main motivation for future semantic/ML detection.

Important: v1 is a small synthetic development dataset, so the v2 settings must later be validated on a held-out and externally sourced test set.
