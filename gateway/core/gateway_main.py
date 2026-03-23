"""Gateway CLI entrypoint (configurable via command-line flags)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from .realtime_gateway import RealtimeGateway, load_config

# 個体識別ログ

# ASR入口ログ
except Exception:
    pass

DEFAULT_CONFIG = Path("/opt/libertycall/config/gateway.yaml")
LOG_DIR = Path("/opt/libertycall/logs")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m gateway.core.gateway_main",
        description="LibertyCall realtime gateway controller",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to gateway.yaml configuration",
    )
    parser.add_argument(
        "--rtp-port",
        type=int,
        dest="rtp_port",
        help="Override RTP listen port",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="Override log level (INFO, DEBUG, etc.)",
    )
    parser.add_argument(
        "--no-asr-controller",
        action="store_true",
        help="Skip launching the auxiliary FastAPI ASR controller",
    )
    return parser


def _setup_logging(level: str = "DEBUG") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "realtime_gateway.log"
    runtime_log = LOG_DIR / "runtime.log"
    log_file.touch(exist_ok=True)
    runtime_log.touch(exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    runtime_handler = logging.FileHandler(runtime_log, encoding="utf-8")
    runtime_handler.setLevel(logging.INFO)
    runtime_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    root.addHandler(stdout_handler)
    root.addHandler(file_handler)
    root.addHandler(runtime_handler)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


async def _maybe_start_asr_controller(gateway: RealtimeGateway) -> Optional[asyncio.Task]:
    try:
        from gateway import asr_controller  # local import to avoid circular deps
        import uvicorn

        asr_controller.set_gateway_instance(gateway)
        server = uvicorn.Server(
            uvicorn.Config(
                app=asr_controller.app,
                host="127.0.0.1",
                port=8000,
                log_level="info",
                access_log=False,
            )
        )
        logging.info("[MAIN] ASR Controller API server starting on http://127.0.0.1:8000")
        return asyncio.create_task(server.serve())
    except Exception as exc:  # pragma: no cover - best-effort dependency
        logging.error("[MAIN] Failed to start ASR controller: %s", exc, exc_info=True)
        return None


async def _async_main(args: argparse.Namespace) -> None:
    import traceback
    try:
        logging.info("[TRACE_INIT] 1: Starting async_main")
        
        # 強制出力Heartbeatタスクを追加
        
        config_path = (args.config or DEFAULT_CONFIG).expanduser().resolve()
        config = load_config(config_path)
        logging.info("[TRACE_INIT] 2: Config loaded")

        log_level = args.log_level or config.get("logging", {}).get("level", "DEBUG")
        _setup_logging(log_level)
        logging.info("[TRACE_INIT] 3: Logging setup done")
        
        # 【BOOT_DIAG】logger生成直後に診断を実行
        logger = logging.getLogger(__name__)
        logging.info("[TRACE_INIT] 4: Boot diag skipped (function removed)")
        logging.info("[TRACE_INIT] 4: Boot diag done")

        rtp_override = args.rtp_port
        if rtp_override:
            logging.info("[MAIN] RTP port override supplied via CLI: %s", rtp_override)
        logging.info("[TRACE_INIT] 5: RTP override checked")

        gateway = RealtimeGateway(config, rtp_port_override=rtp_override)
        logging.info("[TRACE_INIT] 6: RealtimeGateway created")

        asr_task: Optional[asyncio.Task] = None
        if not args.no_asr_controller:
            asr_task = await _maybe_start_asr_controller(gateway)
        logging.info("[TRACE_INIT] 7: ASR controller started (if enabled)")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(gateway.shutdown()))
        logging.info("[TRACE_INIT] 8: Signal handlers set")

        try:
            logging.info("[TRACE_INIT] 9: About to call gateway.start()")
            
            # 呼び出し直前のトレース
            
            try:
                await gateway.start()
                logging.info("[TRACE_INIT] 10: gateway.start() completed")
            except Exception as e:
                import traceback
                raise
        except Exception as e:
            logging.error(f"[FATAL_INIT] Error during gateway.start(): {e}", exc_info=True)
            raise
        finally:
            if asr_task is not None:
                asr_task.cancel()
                
    except Exception:
        err = traceback.format_exc()
        raise


def main(argv: Optional[list[str]] = None) -> int:
    
    # ファイル強制ログ
    except BaseException:
        pass
    
    parser = _build_parser()
    args = parser.parse_args(argv)
    asyncio.run(_async_main(args))
    return 0


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
