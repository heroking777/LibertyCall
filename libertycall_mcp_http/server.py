"""
HTTP MCP server exposing LibertyCall utilities.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from pydantic import BaseModel
from starlette.responses import JSONResponse

from libertycall_mcp_http.tools.files import (
    list_workspace_files,
    read_workspace_file,
)
from libertycall_mcp_http.tools.logs import tail_log_file


class ListFilesArgs(BaseModel):
    path: str | None = None


class TailLogArgs(BaseModel):
    target: Literal["gateway", "asterisk"] | None = None
    path: str | None = None
    lines: int = 200
    grep: str | None = None

SERVER_NAME = "LibertyCall MCP"


def _detect_server_version() -> str:
    if version := os.environ.get("LIBERTYCALL_VERSION"):
        return version
    repo_root = Path(__file__).resolve().parent.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


SERVER_VERSION = _detect_server_version()
DEFAULT_INSTRUCTIONS = (
    "LibertyCall 開発環境のログやファイルを調査するときに利用してください。"
    " read_file, list_files, tail_log の各ツールで必要な情報を取得できます。"
)

mcp_server = FastMCP(name=SERVER_NAME, instructions=DEFAULT_INSTRUCTIONS)


@mcp_server.tool(
    name="list_files",
    description="ワークスペース内のファイル・ディレクトリ一覧を取得します。",
)
def list_files_tool(path: str | None = None) -> list[dict[str, object]]:
    args = ListFilesArgs(path=path)
    return list_workspace_files(path=args.path)


@mcp_server.tool(name="read_file", description="ワークスペース内のファイル内容を読み取ります。")
def read_file_tool(
    path: str,
    offset: int = 0,
    max_bytes: int | None = None,
) -> dict[str, object]:
    return read_workspace_file(path=path, offset=offset, max_bytes=max_bytes)


@mcp_server.tool(
    name="tail_log",
    description="LibertyCall の gateway / Asterisk ログを tail します。path を指定すると任意のログファイルを tail できます。",
)
def tail_log_tool(
    target: Literal["gateway", "asterisk"] | None = None,
    path: str | None = None,
    lines: int = 200,
    grep: str | None = None,
) -> dict[str, object]:
    args = TailLogArgs(target=target, path=path, lines=lines, grep=grep)
    return tail_log_file(target=args.target, path=args.path, lines=args.lines, grep=args.grep)


@mcp_server.custom_route("/health", methods=["GET"])
async def health_check(_request) -> JSONResponse:
    payload = {
        "status": "ok",
        "version": SERVER_VERSION,
        "time": datetime.now(timezone.utc).isoformat(),
        "server": SERVER_NAME,
    }
    return JSONResponse(payload)


async def _run_http_server(host: str, port: int, path: str, transport: str) -> None:
    await mcp_server.run_http_async(
        host=host,
        port=port,
        path=path,
        transport=transport,  # type: ignore[arg-type]
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LibertyCall MCP HTTP server.")
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8000")))
    parser.add_argument("--path", default=os.environ.get("MCP_PATH", "/mcp"))
    parser.add_argument(
        "--transport",
        choices=["http", "streamable-http", "sse"],
        default=os.environ.get("MCP_TRANSPORT", "http"),
    )
    return parser.parse_args()


def main() -> None:
    # CursorのMCP設定ではstdin/stdoutベースのMCPプロトコルを使用
    # 環境変数でHTTPモードが指定されていない場合はstdioモードを使用
    if os.environ.get("MCP_TRANSPORT") or os.environ.get("MCP_HOST") or os.environ.get("MCP_PORT"):
        # HTTPモード
        args = _parse_args()
        path = args.path or "/mcp"
        if not path.startswith("/"):
            path = f"/{path}"

        try:
            asyncio.run(_run_http_server(args.host, args.port, path, args.transport))
        except KeyboardInterrupt:
            pass
    else:
        # stdioモード（CursorのMCP設定で使用）
        mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()

