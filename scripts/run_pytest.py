"""Project-local pytest runner with deterministic plugin loading."""

from __future__ import annotations

import os
import sys


def main() -> int:
    """Run pytest without auto-loading globally installed third-party plugins."""
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["PYTEST_PLUGINS"] = os.environ.get(
        "EXPLAINER_PYTEST_PLUGINS",
        "pytest_asyncio.plugin",
    )

    import pytest

    return pytest.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
