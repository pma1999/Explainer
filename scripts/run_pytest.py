"""Project-local pytest runner with deterministic plugin loading."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _relax_windows_test_dir_modes() -> None:
    """Avoid unreadable pytest temp directories on Windows test runners."""
    if os.name != "nt":
        return

    original_mkdir = os.mkdir

    def mkdir(path, mode=0o777, *args, **kwargs):  # type: ignore[no-untyped-def]
        return original_mkdir(path, 0o777, *args, **kwargs)

    os.mkdir = mkdir  # type: ignore[assignment]


def main() -> int:
    """Run pytest without auto-loading globally installed third-party plugins."""
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["PYTEST_PLUGINS"] = os.environ.get(
        "EXPLAINER_PYTEST_PLUGINS",
        "pytest_asyncio.plugin",
    )
    _relax_windows_test_dir_modes()

    import pytest

    args = sys.argv[1:]
    if not any(arg == "--basetemp" or arg.startswith("--basetemp=") for arg in args):
        repo_root = Path(__file__).resolve().parents[1]
        base_temp = repo_root / "test_output" / f"pytest-basetemp-{os.getpid()}"
        args = [f"--basetemp={base_temp}", *args]

    return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
