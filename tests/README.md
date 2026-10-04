# Product test contract

The main repository contains product tests for RuleGuard, SemanticGuard v2,
benign intent, RiskEngine/policy, providers, DataGuard, gateway/API, audit/DB,
SAFE/ATTACK regressions and production configuration/security.

Install requirements-dev.txt and run either command:

```sh
python -m pytest -q
python -m pytest -m "not research" -q
```

Both commands collect the complete product suite. conftest validates that no
historical research-only module has entered the product test directory. It
raises an explicit UsageError rather than hiding or skipping tests. The research
marker name is retained for compatibility with the existing product command.

Historical research tests, dependencies and implementation source have moved
to the external archive. Their original assertions are preserved there, including
the three historical runtime hash-freeze failures. Restore the historical files
in a separate research workspace before running them. See
[research status](../docs/research/README.md).

Product CI rebuilds the frozen SemanticGuard v2 artifact and runs product tests.
No research dependency, artifact, skip or xfail is needed.
