"""Log-related helpers for the LibertyCall MCP server."""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path
from typing import Deque, Literal

from libertycall_mcp_http import WORKSPACE_ROOT

GATEWAY_LOG_CANDIDATES: tuple[Path, ...] = (
    Path(os.environ.get("LIBERTYCALL_GATEWAY_LOG", WORKSPACE_ROOT / "logs" / "realtime_gateway.log")),
    WORKSPACE_ROOT / "logs" / "gateway.log",
    Path("/var/log/libertycall.log"),
)
ASTERISK_LOG_CANDIDATES: tuple[Path, ...] = (
    Path(os.environ.get("LIBERTYCALL_ASTERISK_LOG", "/var/log/asterisk/messages.log")),
    Path("/var/log/asterisk/messages"),
    Path("/var/log/asterisk/full.log"),
    Path("/var/log/asterisk/full"),
)


def _first_existing(candidates: tuple[Path, ...]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _log_path_for(target: Literal["gateway", "asterisk"]) -> Path:
    candidates = GATEWAY_LOG_CANDIDATES if target == "gateway" else ASTERISK_LOG_CANDIDATES
    log_path = _first_existing(candidates)
    if log_path is None:
        joined = ", ".join(str(p) for p in candidates)
        raise FileNotFoundError(f"ログファイル候補が存在しません (target={target}): {joined}")
    return log_path


def tail_log_file(
    target: Literal["gateway", "asterisk"] | None = None,
    path: str | None = None,
    lines: int = 200,
    grep: str | None = None,
) -> dict[str, object]:
    """
    Return the last ``lines`` lines from the specified log file, optionally filtered by ``grep``.
    
    Either ``path`` or ``target`` must be specified.
    If ``path`` is specified, it takes precedence over ``target``.
    """

    if lines <= 0:
        raise ValueError("lines must be positive")

    if path:
        log_path = Path(path)
    elif target:
        log_path = _log_path_for(target)
    else:
        raise ValueError("Either 'path' or 'target' must be specified")

    if not log_path.exists():
        raise FileNotFoundError(f"ログファイルが存在しません: {log_path}")

    buffer: Deque[str] = deque(maxlen=lines)
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            buffer.append(line.rstrip("\n"))

    rows = list(buffer)
    if grep:
        rows = [line for line in rows if grep in line]

    return {
        "path": str(log_path),
        "lines": rows,
        "total_lines": len(rows),
        "target": target,
        "grep": grep,
    }


__all__ = ["tail_log_file"]

