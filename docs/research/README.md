# Research status: paused

SemanticGuard v3+ research is paused and archived externally; no research
classifier was promoted. The product runs RuleGuard + SemanticGuard
v2 with the benign-intent adapter and semantic threshold `0.51`.

V3+ runtime/helpers, shadow observers, optional research dependencies and
historical tests are absent from this product checkout. No collection,
training, calibration or cloud run is planned.

## Maintainer archive

The local cleanup recorded historical sources and tests in the sibling archive:

```text
LLMBastion-research-archive/
└── local-final-cleanup-20261004/
    ├── source-and-tests/
    └── future-reference/
```

`source-and-tests/` holds historical runtime/helpers, dependencies and tests.
`future-reference/` holds earlier experiment sources and decision manifests;
large artifacts remain elsewhere in the parent archive without duplicate
copies. This maintainer-local archive is not distributed with the repository
and is not required to build or test the product.

To resume historical work, restore sources, tests and their inputs in a separate
research workspace. Use the [product test contract](../../tests/README.md) for
this checkout; archived test failures and research metrics do not describe its
current release gate.
