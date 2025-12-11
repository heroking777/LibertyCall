"""File-oriented helper functions exposed via MCP tools."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Iterable

from libertycall_mcp_http import WORKSPACE_ROOT
from libertycall_mcp_http.tools import relativize, resolve_workspace_path

MAX_DEFAULT_BYTES = 128 * 1024  # 128 KiB


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def list_workspace_files(
    path: str | Path | None = None,
    pattern: str = "*",
    recursive: bool = False,
    include_hidden: bool = False,
    limit: int = 200,
) -> list[dict[str, object]]:
    """
    List files/directories within the LibertyCall workspace.
    """

    base_dir = resolve_workspace_path(path or ".")
    iterator: Iterable[Path]
    if base_dir.is_file():
        iterator = [base_dir]
    else:
        if recursive:
            iterator = base_dir.rglob(pattern)
        else:
            iterator = base_dir.glob(pattern)

    results: list[dict[str, object]] = []
    for entry in iterator:
        if len(results) >= limit:
            break
        try:
            rel = relativize(entry)
        except ValueError:
            continue

        if not include_hidden and _is_hidden(rel):
            continue

        info = {
            "path": str(rel),
            "type": "directory" if entry.is_dir() else "file",
        }
        if entry.is_file():
            info["size"] = entry.stat().st_size
        info["modified"] = entry.stat().st_mtime
        results.append(info)

    return results


def read_workspace_file(
    path: str,
    offset: int = 0,
    max_bytes: int | None = None,
) -> dict[str, object]:
    """
    Read file contents within the workspace, returning UTF-8 text when possible.
    """

    resolved = resolve_workspace_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"{path} does not exist inside the workspace")
    if resolved.is_dir():
        raise IsADirectoryError(f"{path} is a directory")

    read_limit = max_bytes or int(os.environ.get("LIBERTYCALL_MCP_MAX_BYTES", MAX_DEFAULT_BYTES))
    if read_limit <= 0:
        raise ValueError("max_bytes must be positive")

    with resolved.open("rb") as handle:
        if offset:
            handle.seek(offset)
        data = handle.read(read_limit)

    encoding = "utf-8"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = base64.b64encode(data).decode("ascii")
        encoding = "base64"

    return {
        "path": str(relativize(resolved)),
        "offset": offset,
        "bytes_read": len(data),
        "encoding": encoding,
        "content": text,
    }


__all__ = ["list_workspace_files", "read_workspace_file", "WORKSPACE_ROOT"]

