# SemanticGuard v2

This folder contains only the files required to reproduce the selected
SemanticGuard v2 runtime model.

- `build_semantic_guard_v2_artifact.py` builds the runtime artifact from the
  frozen training split.
- `semantic_guard_v2_report.json` contains the held-out evaluation summary.

The generated `.joblib` artifact lives under `app/artifacts/` and is ignored
by Git.
