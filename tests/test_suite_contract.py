"""The product release gate cannot accidentally import historical ML tests."""
import os
from pathlib import Path
import subprocess
import sys

import conftest as contract


def test_all_modules_have_the_correct_suite_marker():
    for path in Path(__file__).parent.glob("test_*.py"):
        required, marked = contract.module_contract(path.read_text(encoding="utf-8-sig"))
        assert not required and not marked, path.name


def test_research_dependency_detection_includes_function_local_imports():
    required, marked = contract.module_contract(
        "import pytest\npytestmark = pytest.mark.research\n"
        "def test_x():\n    from ml import semantic_guard_v3_architecture_capacity\n"
    )
    assert required and marked
    assert contract.module_contract("from ml.build_semantic_guard_v2_artifact import build_selected_model") == (False, False)
    assert contract.module_contract("from app.services import semantic_v3_shadow") == (True, False)
    assert contract.module_contract("from ml.human_collection_workflow import dashboard") == (True, False)


def test_product_collection_rejects_research_instead_of_hiding_it(tmp_path):
    (tmp_path / "conftest.py").write_bytes(Path(contract.__file__).read_bytes())
    (tmp_path / "test_product.py").write_text("def test_product():\n    assert True\n", encoding="utf-8")
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    for selection in ([], ["-m", "not research"]):
        product = subprocess.run([sys.executable, "-m", "pytest", *selection, "-q"],
                                 cwd=tmp_path, env=env, capture_output=True, text=True)
        assert product.returncode == 0, product.stdout + product.stderr
        assert "1 passed" in product.stdout

    research = tmp_path / "test_research.py"
    for source in (
        "import pytest\npytestmark = pytest.mark.research\nimport torch\n",
        "import torch\ndef test_research():\n    assert True\n",
    ):
        research.write_text(source, encoding="utf-8")
        for selection in ([], ["-m", "not research"]):
            invalid = subprocess.run([sys.executable, "-m", "pytest", *selection, "-q"],
                                     cwd=tmp_path, env=env, capture_output=True, text=True)
            assert invalid.returncode == 4
            assert "Product suite contains research-only module" in invalid.stderr
