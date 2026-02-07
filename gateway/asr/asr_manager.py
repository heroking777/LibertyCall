"""ASR handlers shared between AICore and realtime gateway."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
import audioop

TRACE_FD = os.open("/tmp/asr_manager.trace", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)

from .audio_processor import AudioProcessor
from .asr_stream_handler import ASRStreamHandler


def init_asr(core):
    core.streaming_enabled = True
    if not hasattr(core, "_asr_stream_handler"):
        class _DummyManager:
            def __init__(self, ai_core):
                self.ai_core = ai_core
                self.logger = logging.getLogger(__name__)
                self.streaming_enabled = True
                self.asr_handler_enabled = False

            def _get_effective_call_id(self, addr=None):
                return ai_core.current_call_id if hasattr(ai_core, "current_call_id") else None

        core._asr_stream_handler = ASRStreamHandler(_DummyManager(core))


def on_new_audio(core, call_id: str, pcm16k_bytes: bytes) -> None:
    if not hasattr(core, "_asr_stream_handler"):
        init_asr(core)
    handler = core._asr_stream_handler
    handler.handle_new_audio(core, call_id, pcm16k_bytes)

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from gateway.realtime_gateway import RealtimeGateway


@dataclass
class ASRManagerConfig:
    """ASRマネージャーの設定"""
    streaming_enabled: bool = True
    asr_handler_enabled: bool = True
    batch_mode_enabled: bool = True


class ASRManager:
    """ASRマネージャー - 音声処理の調整役"""
    
    def __init__(self, gateway: RealtimeGateway, config: ASRManagerConfig):
        self.gateway = gateway
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 音声プロセッサーを作成
        self.audio_processor = AudioProcessor()
        
        # 状態管理
        self._active_calls = set()
        self._call_addr_map = {}
        
        self.logger.info("[ASRManager] Initialized with AudioProcessor")
    
    def _get_effective_call_id(self, addr: Tuple[str, int]) -> Optional[str]:
        """有効なcall_idを取得"""
        if addr in self._call_addr_map:
            return self._call_addr_map[addr]
        
        if not self.call_id:
            return None
        
        return self.call_id
    
    def _register_active_call(self, call_id: str, addr: Tuple[str, int]) -> None:
        """アクティブコールを登録"""
        self._active_calls.add(call_id)
        if addr:
            self._call_addr_map[addr] = call_id


class GatewayASRManager:
    """ASRマネージャー - 音声処理の調整役"""
    
    def __init__(self, gateway: RealtimeGateway):
        self.gateway = gateway
        self.logger = logging.getLogger(__name__)
        
        # 音声プロセッサーを作成
        try:
            self.audio_processor = AudioProcessor()
            os.write(2, b"[TRACE_AUDIO_PROC_INIT] Success\n")
        except Exception as e:
            os.write(2, f"[TRACE_AUDIO_PROC_INIT] Error: {e}\n".encode())
            raise
        
        # 状態管理
        self._active_calls = set()
        self._call_addr_map = {}
        
        # ストリーミングハンドラー
        upstream_handler = getattr(gateway, 'stream_handler', None)
        if upstream_handler is None:
            upstream_handler = ASRStreamHandler(self)
            setattr(gateway, 'stream_handler', upstream_handler)
        self.stream_handler = upstream_handler
        self.batch_handler = getattr(gateway, 'batch_handler', None)
        
        if self.batch_handler is None:
            self.logger.warning("[GatewayASRManager] batch_handler is None")
        
        # カウンター
        self._stream_chunk_counter = 0
        self._last_feed_time = 0.0

        # セッション管理
        self.active_sessions: Dict[str, Dict[str, object]] = {}
        self._session_lock = asyncio.Lock()
        self._call_addr_map: Dict[Tuple[str, int], str] = {}
        self._ssrc_call_map: Dict[int, str] = {}
        self._rtp_packet_count: Dict[str, int] = {}
        
        self.logger.info("[GatewayASRManager] Initialized")

    async def start_asr_for_call(self, call_id: str, channel_vars: Optional[Dict[str, str]] = None) -> bool:
        channel_vars = channel_vars or {}
        async with self._session_lock:
            if call_id in self.active_sessions:
                self.logger.warning("[GatewayASRManager] Session already active for call_id=%s", call_id)
                return True

            try:
                remote_ip = channel_vars.get("variable_remote_media_ip")
                remote_port = channel_vars.get("variable_remote_media_port")
                ssrc = channel_vars.get("variable_rtp_use_ssrc")
                codec = channel_vars.get("variable_read_codec_name", "PCMU")

                if not remote_ip or not remote_port:
                    self.logger.error("[GatewayASRManager] Missing RTP address info for call_id=%s", call_id)
                    return False

                rtp_addr = (remote_ip, int(remote_port))
                session_info = {
                    "call_id": call_id,
                    "channel_vars": channel_vars,
                    "started_at": datetime.utcnow(),
                    "audio_processor": self.audio_processor,
                    "rtp_addr": rtp_addr,
                    "ssrc": int(ssrc) if ssrc else None,
                    "codec": codec,
                }

                self.active_sessions[call_id] = session_info
                self._call_addr_map[rtp_addr] = call_id
                if session_info["ssrc"] is not None:
                    self._ssrc_call_map[session_info["ssrc"]] = call_id

                self.logger.info(
                    "[GatewayASRManager] ✅ Started ASR session call_id=%s codec=%s addr=%s",
                    call_id,
                    codec,
                    rtp_addr,
                )
                return True
            except Exception as exc:
                self.logger.error(
                    "[GatewayASRManager] Failed to start ASR for call_id=%s: %s",
                    call_id,
                    exc,
                    exc_info=True,
                )
                return False

    async def stop_asr_for_call(self, call_id: str) -> None:
        async with self._session_lock:
            session = self.active_sessions.pop(call_id, None)
            if not session:
                self.logger.warning("[GatewayASRManager] No active ASR session for call_id=%s", call_id)
                return

            rtp_addr = session.get("rtp_addr")
            ssrc = session.get("ssrc")

            if rtp_addr and rtp_addr in self._call_addr_map:
                self._call_addr_map.pop(rtp_addr, None)
            if ssrc and ssrc in self._ssrc_call_map:
                self._ssrc_call_map.pop(ssrc, None)

            self._rtp_packet_count.pop(call_id, None)

            self.logger.info("[GatewayASRManager] 🛑 Stopped ASR session call_id=%s", call_id)

    async def process_rtp_audio_for_call(self, call_id: str, packet: bytes) -> None:
        session = self.active_sessions.get(call_id)
        if not session:
            return

        processor: AudioProcessor = session["audio_processor"]  # type: ignore[assignment]
        self._rtp_packet_count[call_id] = self._rtp_packet_count.get(call_id, 0) + 1

        if self._rtp_packet_count[call_id] % 100 == 0:
            self.logger.debug(
                "[GatewayASRManager] RTP packets processed call_id=%s count=%s",
                call_id,
                self._rtp_packet_count[call_id],
            )

        try:
            processed = processor.process_rtp_audio(packet, addr=session.get("rtp_addr", ("0.0.0.0", 0)))
            if processed and self.stream_handler:
                try:
                    rms_16k = audioop.rms(processed, 2)
                except Exception:
                    rms_16k = 0
                self.stream_handler.handle_streaming_chunk(processed, rms_16k)
        except Exception as exc:
            self.logger.error(
                "[GatewayASRManager] Error processing RTP for call_id=%s: %s",
                call_id,
                exc,
                exc_info=True,
            )
            await self.stop_asr_for_call(call_id)

    def process_rtp_audio(self, data: bytes, addr: Tuple[str, int]):
        try:
            # 1. エントリログ
            os.write(TRACE_FD, b"[FINAL_OP_1] Enter\n")
            
            os.write(TRACE_FD, b"[TRACE_AP_REF_BEFORE]\n")
            
            # 2. 直接アクセス（hasattrは使わない）
            # もし self.audio_processor が存在しなければ AttributeError へ飛ぶ
            p = self.audio_processor
            
            os.write(TRACE_FD, b"[TRACE_AP_REF_AFTER]\n")
            
            # 3. 取得成功ログ
            os.write(TRACE_FD, f"[FINAL_OP_2] ProcID={id(p)}\n".encode())

            if p is not None:
                os.write(TRACE_FD, b"[TRACE_AP_CALL_BEFORE]\n")
                
                try:
                    fn = p.process_rtp_audio
                    os.write(
                        TRACE_FD,
                        (
                            "[TRACE_AP_IMPL] "
                            f"class={p.__class__} "
                            f"module={getattr(fn, '__module__', None)} "
                            f"qualname={getattr(fn, '__qualname__', None)} "
                            f"file={getattr(getattr(fn, '__code__', None), 'co_filename', None)} "
                            f"line={getattr(getattr(fn, '__code__', None), 'co_firstlineno', None)}"
                            "\n"
                        ).encode()
                    )
                except BaseException as e:
                    os.write(TRACE_FD, f"[TRACE_AP_IMPL_ERROR] {e}\n".encode())
                
                # 4. AudioProcessor 呼び出し
                processed = p.process_rtp_audio(data, addr)
                
                os.write(
                    TRACE_FD,
                    f"[TRACE_AP_RET] ap_id={id(p)} ret_type={type(processed)} ret_len={len(processed) if processed else 0}\n".encode()
                )
                os.write(TRACE_FD, b"[TRACE_AP_CALL_AFTER]\n")
                
                # 5. 戻り値確認ログ
                if processed:
                    os.write(TRACE_FD, f"[FINAL_OP_3] Processed size={len(processed)}\n".encode())
                    if p.stream_handler:
                        os.write(TRACE_FD, b"[TRACE_BEFORE_HANDLER]\n")
                        p.stream_handler.handle_streaming_chunk(processed)
                        os.write(TRACE_FD, b"[TRACE_AFTER_HANDLER]\n")
                    else:
                        os.write(TRACE_FD, b"[TRACE_NO_HANDLER]\n")
                else:
                    # VADで落とされた場合はここに来る
                    os.write(TRACE_FD, b"[TRACE_VAD_REJECTED]\n")
            else:
                os.write(TRACE_FD, b"[FINAL_OP_ERR] Processor is None\n")

        except BaseException as e:
            import traceback
            # AttributeError, NameError, その他全ての致命的エラーを捕捉
            err = f"[FINAL_OP_FATAL] {type(e).__name__}: {e}\n{traceback.format_exc()}\n"
            os.write(2, err.encode())

    def resolve_call_id(self, addr: Tuple[str, int], ssrc: Optional[int] = None) -> Optional[str]:
        if ssrc is not None and ssrc in self._ssrc_call_map:
            return self._ssrc_call_map.get(ssrc)
        return self._call_addr_map.get(addr)
    
    def _get_effective_call_id(self, addr: Optional[Tuple[str, int]] = None) -> Optional[str]:
        """有効なcall_idを取得"""
        if addr and addr in self._call_addr_map:
            return self._call_addr_map[addr]
        
        if getattr(self.gateway, "call_id", None):
            return self.gateway.call_id
        
        return None
    
    def _register_active_call(self, call_id: str, addr: Tuple[str, int]) -> None:
        """アクティブコールを登録"""
        self._active_calls.add(call_id)
        if addr:
            self._call_addr_map[addr] = call_id
