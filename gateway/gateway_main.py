"""Main entrypoint for the realtime gateway."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import threading
from pathlib import Path
from typing import Any

import uvicorn

from libertycall.gateway.core.gateway_config_manager import GatewayConfigManager
from libertycall.gateway.realtime_gateway import RealtimeGateway


def _load_asr_controller_module():
    """Import ASR controller lazily so --help works without FastAPI."""
    try:
        from gateway import asr_controller  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on runtime env
        raise RuntimeError(
            "FastAPI (required for gateway.asr_controller) is not installed. "
            "Install dependencies via 'pip install -r requirements.txt' to run the gateway."
        ) from exc

    return asr_controller


def main() -> None:
    GatewayConfigManager.setup_environment()

    log_dir = Path("/opt/libertycall/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                "/opt/libertycall/logs/realtime_gateway.log", encoding="utf-8"
            ),
        ],
    )

    print("[MAIN_DEBUG] main function started", flush=True)

    parser = argparse.ArgumentParser(description="Liberty Call Realtime Gateway")
    parser.add_argument(
        "--rtp_port",
        type=int,
        default=None,
        help="Override RTP listen port (default: from config or env LC_RTP_PORT)",
    )
    parser.add_argument(
        "--uuid",
        type=str,
        required=False,
        default=None,
        help="Unique identifier for this gateway instance (passed from event listener)",
    )
    args = parser.parse_args()

    if args.uuid:
        print(f"[GATEWAY_INIT] Starting with UUID: {args.uuid}", flush=True)

    config_path = Path("/opt/libertycall") / "config" / "gateway.yaml"
    config = GatewayConfigManager.load_config(config_path)

    gateway = RealtimeGateway(config, rtp_port_override=args.rtp_port)
    print(f"[MAIN_DEBUG] RealtimeGateway created, uuid={args.uuid}", flush=True)
    gateway.uuid = args.uuid

    asr_controller_module = _load_asr_controller_module()
    asr_controller_module.set_gateway_instance(gateway)

    def _run_asr_controller(app: Any) -> None:
        logger = logging.getLogger(__name__)
        try:
            logger.info("[ASR_CONTROLLER] Starting FastAPI server on 127.0.0.1:8000")
            config_obj = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=8000,
                log_level="info",
                access_log=True,
            )
            server = uvicorn.Server(config_obj)
            server.run()
        except Exception:
            logger.exception("[ASR_CONTROLLER] FastAPI server terminated due to error")

    asr_thread = threading.Thread(
        target=_run_asr_controller,
        args=(asr_controller_module.app,),
        name="ASRControllerThread",
        daemon=True,
    )
    asr_thread.start()

    def signal_handler(sig, frame):
        logger = logging.getLogger(__name__)
        logger.info("[SIGNAL] Received signal %s, initiating shutdown...", sig)
        asyncio.create_task(gateway.shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(gateway.start())
    except KeyboardInterrupt:
        pass
    finally:
        logger = logging.getLogger(__name__)
        logger.info("[EXIT] Gateway stopped")


if __name__ == "__main__":
    main()
