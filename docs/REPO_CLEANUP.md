# Product repository boundary

This checkout contains product source/configuration, migrations, SemanticGuard
v2 reproducibility inputs, product tests/fixtures, documentation, CI and current
evaluator scripts. The stable decision path is RuleGuard + SemanticGuard v2
with the benign-intent adapter; the semantic threshold remains `0.51`.

## Product and research

SemanticGuard v3+ experiments, shadow runtime/helpers, optional research
dependencies and historical tests are outside this checkout. Research is paused;
see [research status](research/README.md).

Both ordinary pytest and the product marker command collect the complete
product suite. Collection rejects research-only modules in the product test
directory instead of hiding or skipping them:

```powershell
python -m pytest -q
python -m pytest -m "not research" -q
```

See [test setup and recorded release baseline](../README.md#tests) and
[test contracts](../tests/README.md).

## Local files and generated outputs

Local environment files, databases, virtual environments, generated model
artifacts and `reports/` outputs are excluded from publication by `.gitignore`.
The model artifact is rebuilt from the frozen training split; its committed
metadata and reproducibility inputs remain in the product repository.

The maintainer's cleanup preserved local `.env`, `llmbastion.db`, `.git` and the
registered `.kilo/` worktree. These are local workspace details, not requirements
for a fresh clone.
