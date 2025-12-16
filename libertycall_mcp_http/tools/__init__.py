"""Utility helpers for LibertyCall MCP tools."""

from __future__ import annotations

from pathlib import Path

from libertycall_mcp_http import WORKSPACE_ROOT


def resolve_workspace_path(value: str | Path, *, root: Path | None = None) -> Path:
    """
    Resolve ``value`` to an absolute path that must live within the workspace root.

    Raises:
        ValueError: If the resolved path escapes the workspace root.
    """

    base = Path(root or WORKSPACE_ROOT).resolve()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"path {candidate} is outside of the workspace root {base}") from exc

    return candidate


def relativize(path: Path, *, root: Path | None = None) -> Path:
    """Return a path relative to the workspace root."""

    base = Path(root or WORKSPACE_ROOT).resolve()
    path = Path(path).resolve()
    return path.relative_to(base)


__all__ = ["resolve_workspace_path", "relativize"]












