"""Shim module that exposes the legacy realtime_gateway implementation."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_legacy_module() -> ModuleType:
    legacy_path = Path(__file__).resolve().parents[2] / "gateway" / "realtime_gateway.py"
    spec = importlib.util.spec_from_file_location(
        "gateway._legacy_realtime_gateway", legacy_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load legacy realtime_gateway module at {legacy_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_legacy_module = _load_legacy_module()

for _name, _value in _legacy_module.__dict__.items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value

__all__ = getattr(
    _legacy_module,
    "__all__",
    sorted(name for name in globals() if not name.startswith("_")),
)
