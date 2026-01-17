"""Package entrypoint that delegates to the legacy gateway CLI script."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_legacy_module():
    legacy_path = Path(__file__).resolve().parents[3] / "gateway" / "gateway_main.py"
    spec = importlib.util.spec_from_file_location(
        "libertycall.gateway._legacy_gateway_main", legacy_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load legacy gateway_main module at {legacy_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_legacy = _load_legacy_module()
main = getattr(_legacy, "main")

__all__ = ["main"]


if __name__ == "__main__":
    main()
