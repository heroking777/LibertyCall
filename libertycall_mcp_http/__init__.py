"""
LibertyCall MCP HTTP package utilities.

This module exposes shared constants so the MCP server and its tools can
consistently refer to the same project root, even when invoked via ngrok.
"""

from __future__ import annotations

import os
from pathlib import Path

# 環境変数で制御可能。未設定の場合は / をデフォルトとして使用
# これにより /tmp などの上位ディレクトリにもアクセス可能
_DEFAULT_WORKSPACE = os.environ.get("LIBERTYCALL_WORKSPACE_ROOT", "/")
WORKSPACE_ROOT = Path(_DEFAULT_WORKSPACE).resolve()
"""Root directory for the LibertyCall workspace."""


def get_workspace_root() -> Path:
    """Return the absolute workspace root directory."""
    return WORKSPACE_ROOT


__all__ = ["WORKSPACE_ROOT", "get_workspace_root"]



