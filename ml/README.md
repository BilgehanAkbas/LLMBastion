# ML experiments

## SemanticGuard v2

The runtime SemanticGuard model is trained with the checked-in multilingual v2 splits:

```powershell
python ml\train_semantic_guard_v2.py
```

The script fits word and character TF-IDF + Logistic Regression candidates on `train.jsonl`, chooses a model and threshold on `validation.jsonl`, then reports the held-out-test metrics. The selected pipeline is written to `app/artifacts/semantic_guard_v2.joblib`, which is intentionally ignored by Git.

The committed `semantic_guard_v2_report.json` records the reproducible selected configuration and final evaluation result.

## Earlier experiments

The remaining scripts document the project’s earlier baseline, calibration, and public-benchmark experiments. They are retained for provenance; SemanticGuard v2 is the runtime model.
