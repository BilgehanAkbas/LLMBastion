# LLMBastion multilingual prompt-injection dataset

This is the final dataset package used by SemanticGuard v2.

- 1,200 synthetic prompts: 600 attack and 600 safe
- Languages: 540 Turkish, 540 English, 120 Turkish-English mixed
- 15 prompt-injection attack families
- Train / validation / held-out-test split: 840 / 180 / 180

`data/` contains the three final splits. `schema.json`, `dataset_spec_v1.md`, `FINAL_DATASET_REPORT.json`, and `SPLIT_REPORT.json` describe the dataset contract, composition, and leakage checks.

The split is group-aware: paired examples and near-duplicates were kept in one split. The split report records zero cross-split pairs and zero detected near-duplicates at the configured 0.85 similarity threshold.

The test labels are included to make the reported result reproducible. Do not tune a model, preprocessing, or threshold with this split; use it only for final reporting.
