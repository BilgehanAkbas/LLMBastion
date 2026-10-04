# Product repository boundary

The main repository contains production source/configuration, migrations,
SemanticGuard v2 reproducibility inputs, product tests/fixtures, documentation,
CI and dependency files. The v2 artifact and thresholds are unchanged.

Root SemanticGuard v3 experiment directories have been removed. Small historical
sources, manifests and summaries were moved to the sibling research archive at
`LLMBastion-research-archive/local-final-cleanup-20261004/future-reference/`.
Superseded generated outputs were deleted. Previously archived large files were
not copied again. See [research status](research/README.md).

The main publication set contains only product source, tests, documentation and
current evaluator scripts. V3 shadow runtime/helpers, optional dependencies and
historical tests are in the external archive under `source-and-tests/`.
Both ordinary pytest and the existing product marker command run the complete
product suite; research modules in the product test directory cause an error.

Local .env, llmbastion.db and .git are preserved. The small registered Git
worktree under .kilo/ is retained because it contains another product checkout
and is referenced by .git worktree metadata. It is not a research experiment.

The current product command is `python -m pytest -m "not research" -q`.
No model training, threshold change, staging, commit or push is part of cleanup.
