# ML Baseline v1

Goal: test whether a small semantic text classifier can catch attacks that the regex RuleGuard misses.

```text
Prompt
  ↓
TF-IDF
  ↓
Logistic Regression
  ↓
Attack probability
```

TF-IDF converts text into numeric features. Logistic Regression learns a binary `safe` vs `attack` decision from those features.

This is intentionally simpler than BERT/Transformers because it is fast, CPU-friendly, easy to understand, and gives us a baseline before heavier models.

## Data separation

- `training_v1.jsonl`: 200 synthetic training prompts
- `evaluation/prompt_injection_v1.jsonl`: existing 100-prompt unseen test set

The script checks for exact train/test duplicates.

## Run

```powershell
pip install -r requirements.txt
python ml\train_and_compare.py
```

It compares:

- Regex only
- ML only
- Regex + ML (simple OR hybrid)

using Precision, Recall, F1, FPR and FNR.

Both datasets are synthetic, so these scores are experimental—not production claims.


## Threshold calibration

Run:

```powershell
python ml\calibrate_threshold.py
```

The script sweeps multiple ML thresholds and compares ML-only and hybrid Precision, Recall, F1, FPR and FNR. It also prints false-positive and false-negative examples for the best experimental candidate.

The result is provisional because both datasets are synthetic.

## External held-out check

After calibrating the ML threshold on the internal synthetic validation set, run an external benchmark without changing the threshold:

```powershell
pip install datasets
python ml\external_eval_deepset.py
```

This uses the public `deepset/prompt-injections` test split and compares Regex only, ML only, and Hybrid OR. The ML threshold stays fixed at `0.60`.

Do not tune the threshold based on this benchmark if you want to preserve it as a held-out generalization check.


## Public benchmark v2

For a stronger experiment, use the public `S-Labs/prompt-injection-dataset`:

```powershell
python ml\public_benchmark_slabs.py
```

The script:

1. trains TF-IDF + Logistic Regression on the dataset's `train` split,
2. selects ML-only and Hybrid thresholds using only `validation`,
3. evaluates Regex, ML and Hybrid on `test`,
4. prints test false positives and false negatives.

The test split is not used for training or threshold selection.

This benchmark is English-only, so Turkish coverage still needs a separate evaluation.


## Clean public benchmark

The S-Labs dataset contains exact duplicates across splits. To measure how much this affects the result, run:

```powershell
python ml\public_benchmark_slabs_clean.py
```

This version removes:

- train duplicates from validation,
- train duplicates from test,
- cleaned-validation duplicates from test,

before threshold calibration and final test evaluation.

This gives a stricter estimate than the raw split benchmark.
