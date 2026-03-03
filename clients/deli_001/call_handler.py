"""
デリ専用 通話ハンドラ
ASR(ws_sink_deli) → 会話エンジン → TTS → FreeSWITCH

ws_sink_deli.py から呼ばれるエントリポイント
"""
import logging
import asyncio
import aiohttp
import json
import os
from typing import Optional, Dict
from datetime import datetime, timedelta, timezone

from .models import Session, State, JST
from .engine_core import ConversationEngine
from .engine_handlers import register_handlers

# ハンドラ登録（__init__.pyでも実行済みだが念のため）
register_handlers(ConversationEngine)

logger = logging.getLogger("deli_call_handler")

# テナントID（デリ専用は固定）
DELI_TENANT_ID = "bcc1ca5c-5ab2-49a8-9eeb-2295c2f5737f"

# FreeSWITCH ESL or API
FS_HOST = "127.0.0.1"
FS_ESL_PORT = 8021
FS_ESL_PASS = "ClueCon"

# TTS設定（Google Cloud TTS）
TTS_ENABLED = True
TTS_VOICE = "ja-JP-Neural2-B"
TTS_SAMPLE_RATE = 8000
AUDIO_DIR = "/opt/libertycall/clients/deli_001/audio"


class DeliCallManager:
    """全通話セッションを管理"""

    def __init__(self):
        self.sessions: Dict[str, ConversationEngine] = {}
        self._tts_client = None

    def _get_tts_client(self):
        if self._tts_client is None and TTS_ENABLED:
            try:
                from google.cloud import texttospeech
                self._tts_client = texttospeech.TextToSpeechClient()
            except Exception as e:
                logger.error(f"TTS client init error: {e}")
        return self._tts_client

    async def on_call_start(
        self, call_uuid: str, caller_number: str
    ) -> list[str]:
        """着信時に呼ばれる"""
        logger.info(
            f"[{call_uuid}] 着信: {caller_number}"
        )
        session = Session(
            call_uuid=call_uuid,
            tenant_id=DELI_TENANT_ID,
            caller_number=caller_number,
        )
        engine = ConversationEngine(session)
        self.sessions[call_uuid] = engine

        replies = await engine.start()

        # TTS生成＆再生
        for text in replies:
            await self._speak(call_uuid, text)

        return replies

    async def on_transcript(
        self, call_uuid: str, text: str
    ) -> list[str]:
        """ASRテキスト受信時に呼ばれる"""
        engine = self.sessions.get(call_uuid)
        if not engine:
            logger.warning(
                f"[{call_uuid}] セッション未発見"
            )
            return []

        replies = await engine.on_transcript(text)

        for reply in replies:
            await self._speak(call_uuid, reply)

        # 通話終了判定
        if engine.s.state in (State.DONE, State.ERROR):
            logger.info(
                f"[{call_uuid}] 通話終了: {engine.s.state}"
            )
            # 少し待ってからハングアップ
            asyncio.get_event_loop().call_later(
                5.0, lambda: asyncio.ensure_future(
                    self._hangup(call_uuid)
                )
            )

        return replies

    async def on_call_end(self, call_uuid: str):
        """通話終了時のクリーンアップ"""
        engine = self.sessions.pop(call_uuid, None)
        if engine:
            # 会話ログ保存
            await self._save_log(call_uuid, engine)
            await engine.close()
            logger.info(f"[{call_uuid}] セッション終了")

    async def _speak(self, call_uuid: str, text: str):
        """TTS生成 → wavファイル → FreeSWITCH playback"""
        logger.info(f"[{call_uuid}] TTS: {text}")

        wav_path = await self._tts_to_file(
            call_uuid, text
        )
        if wav_path:
            await self._fs_playback(call_uuid, wav_path)

    async def _tts_to_file(
        self, call_uuid: str, text: str
    ) -> Optional[str]:
        """Google TTS でwavファイル生成"""
        client = self._get_tts_client()
        if not client:
            logger.warning("TTS client not available")
            return None

        try:
            from google.cloud import texttospeech

            response = client.synthesize_speech(
                input=texttospeech.SynthesisInput(text=text),
                voice=texttospeech.VoiceSelectionParams(
                    language_code="ja-JP",
                    name=TTS_VOICE,
                ),
                audio_config=texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                    sample_rate_hertz=TTS_SAMPLE_RATE,
                ),
            )

            os.makedirs(AUDIO_DIR, exist_ok=True)
            ts = datetime.now(JST).strftime("%H%M%S%f")
            filename = f"{call_uuid}_{ts}.wav"
            wav_path = os.path.join(AUDIO_DIR, filename)

            with open(wav_path, "wb") as f:
                f.write(response.audio_content)

            logger.debug(
                f"TTS wav: {wav_path} "
                f"({len(response.audio_content)} bytes)"
            )
            return wav_path

        except Exception as e:
            logger.error(f"TTS error: {e}")
            return None

    async def _fs_playback(
        self, call_uuid: str, wav_path: str
    ):
        """FreeSWITCH に playback 指示"""
        try:
            cmd = (
                f"bgapi uuid_broadcast "
                f"{call_uuid} "
                f"playback::{wav_path} aleg"
            )
            reader, writer = await asyncio.open_connection(
                FS_HOST, FS_ESL_PORT
            )
            # ESL認証
            await reader.readuntil(b"\n\n")
            writer.write(
                f"auth {FS_ESL_PASS}\n\n".encode()
            )
            await writer.drain()
            await reader.readuntil(b"\n\n")

            # コマンド送信
            writer.write(f"{cmd}\n\n".encode())
            await writer.drain()
            resp = await asyncio.wait_for(
                reader.readuntil(b"\n\n"), timeout=5
            )
            logger.debug(f"FS response: {resp.decode()}")

            writer.close()
            await writer.wait_closed()

        except Exception as e:
            logger.error(f"FS playback error: {e}")

    async def _hangup(self, call_uuid: str):
        """FreeSWITCH に hangup 指示"""
        try:
            reader, writer = await asyncio.open_connection(
                FS_HOST, FS_ESL_PORT
            )
            await reader.readuntil(b"\n\n")
            writer.write(
                f"auth {FS_ESL_PASS}\n\n".encode()
            )
            await writer.drain()
            await reader.readuntil(b"\n\n")

            cmd = f"bgapi uuid_kill {call_uuid}"
            writer.write(f"{cmd}\n\n".encode())
            await writer.drain()
            await reader.readuntil(b"\n\n")

            writer.close()
            await writer.wait_closed()
            logger.info(f"[{call_uuid}] hangup sent")

        except Exception as e:
            logger.error(f"hangup error: {e}")

    async def _save_log(
        self, call_uuid: str, engine: ConversationEngine
    ):
        """会話ログをAPIに保存"""
        try:
            async with aiohttp.ClientSession() as http:
                await http.post(
                    "http://localhost:8100/api/call_logs",
                    json={
                        "tenant_id": engine.s.tenant_id,
                        "call_uuid": call_uuid,
                        "caller_number": engine.s.caller_number,
                        "final_state": engine.s.state.value,
                        "history": engine.s.history,
                    }
                )
        except Exception as e:
            logger.warning(f"save log error: {e}")


# シングルトン
call_manager = DeliCallManager()
