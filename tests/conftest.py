"""Product publication boundary; research tests belong in the external archive."""
import ast
from pathlib import Path

import pytest


_RESEARCH_PACKAGES = {
    "torch", "transformers", "accelerate", "huggingface_hub", "datasets",
    "pyarrow", "pandas", "langdetect",
}


def research_dependency(module: str) -> bool:
    return (
        module.split(".")[0] in _RESEARCH_PACKAGES
        or module == "ml"
        or (module.startswith("ml.") and module != "ml.build_semantic_guard_v2_artifact")
        or module.startswith("semantic_guard_v3_")
        or module == "app.services.semantic_v3_shadow"
    )


def module_contract(source: str) -> tuple[bool, bool]:
    """Return (requires research, marked research) without importing the file."""
    tree = ast.parse(source)
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module in {"ml", "app.services"}:
                modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
            else:
                modules.append(node.module or "")
    paths = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
             and isinstance(node.value, str)]
    required = any(research_dependency(module) for module in modules) or any(
        path.startswith(("semantic_guard_v3_", "app/artifacts/semantic_guard_v3_",
                         "data/semantic_v3_shadow")) for path in paths
    )
    marked = any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets)
        and any(isinstance(value, ast.Attribute)
                and ast.unparse(value) == "pytest.mark.research" for value in ast.walk(node.value))
        for node in tree.body
    )
    return required, marked


def pytest_configure(config):
    for path in Path(__file__).parent.rglob("test_*.py"):
        required, marked = module_contract(path.read_text(encoding="utf-8-sig"))
        if required or marked:
            raise pytest.UsageError(
                f"Product suite contains research-only module: {path.name}. "
                "Keep historical research in the external archive."
            )
