"""Project-local shim so `python -m pytest` uses the stable test runner setup."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parent
_THIS_FILE = Path(__file__).resolve()
_RUNNING_AS_MAIN = __name__ == "__main__"


def _is_repo_path(path_entry: str) -> bool:
    try:
        path = Path.cwd() if path_entry == "" else Path(path_entry)
        return path.resolve() == _REPO_ROOT
    except OSError:
        return False


def _relax_windows_test_dir_modes() -> None:
    if os.name != "nt":
        return

    original_mkdir = os.mkdir

    def mkdir(path, mode=0o777, *args, **kwargs):  # type: ignore[no-untyped-def]
        return original_mkdir(path, 0o777, *args, **kwargs)

    os.mkdir = mkdir  # type: ignore[assignment]


def _configure_pytest() -> None:
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    os.environ.setdefault("PYTEST_PLUGINS", "pytest_asyncio.plugin")
    _relax_windows_test_dir_modes()


def _with_default_basetemp(args: list[str]) -> list[str]:
    if any(arg == "--basetemp" or arg.startswith("--basetemp=") for arg in args):
        return args
    if "--basetemp" in os.environ.get("PYTEST_ADDOPTS", ""):
        return args

    base_temp = _REPO_ROOT / "test_output" / f"pytest-basetemp-{os.getpid()}"
    return [f"--basetemp={base_temp}", *args]


def _load_real_pytest() -> ModuleType:
    current = sys.modules.get("pytest")
    if current is not None:
        current_file = getattr(current, "__file__", None)
        if current_file and Path(current_file).resolve() == _THIS_FILE:
            sys.modules.pop("pytest", None)

    original_path = list(sys.path)
    sys.path[:] = [entry for entry in original_path if not _is_repo_path(entry)]
    try:
        return importlib.import_module("pytest")
    finally:
        sys.path[:] = original_path


_configure_pytest()
_real_pytest = _load_real_pytest()
sys.modules["pytest"] = _real_pytest

if _RUNNING_AS_MAIN:
    raise SystemExit(_real_pytest.main(_with_default_basetemp(sys.argv[1:])))

globals().update(_real_pytest.__dict__)
