#!/usr/bin/env python3
"""
ws_sink_deli.py - デリヘル専用ASR WebSocket Server
Google Cloud Speech-to-Text + 業界用語辞書（speech_contexts）
既存回線（ws_sink_optimized.py:9000）とは完全に独立
"""

import asyncio
import socket
import aiohttp
import websockets
import logging
import time
import threading
import queue
from google.cloud import speech_v1 as speech
from google.api_core.client_options import ClientOptions

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("deli_asr")

DELI_TENANT_ID = "bcc1ca5c-5ab2-49a8-9eeb-2295c2f5737f"
RESERVATION_API = "http://localhost:8100"
AUDIO_BASE = "/opt/navic/clients/test/fixed"

GASR_SAMPLE_RATE = 8000
WS_PORT = 9001  # デリ専用ポート（既存9000と分離）

# ========================================
# デリヘル業界用語辞書
# ========================================
DELI_SPEECH_CONTEXTS = [
    # --- サービス・オプション ---
    speech.SpeechContext(
        phrases=[
            "電マ", "パイズリ", "素股", "即尺", "即プレ",
            "マットプレイ", "洗体", "密着", "ごっくん",
            "オプション", "基本プレイ", "追加オプション",
            "ローター", "バイブ", "コスプレ", "聖水",
            "パンスト", "ノーパン", "ディープキス",
            "トップレス", "全裸",
        ],
        boost=18.0,
    ),
    # --- コース関連 ---
    speech.SpeechContext(
        phrases=[
            "フリー", "指名", "本指名", "写真指名",
            "ロング", "ショート", "延長",
            "60分", "90分", "120分", "70分", "80分", "100分",
            "60分コース", "90分コース", "120分コース",
            "コース", "お時間",
        ],
        boost=15.0,
    ),
    # --- 場所関連 ---
    speech.SpeechContext(
        phrases=[
            "自宅", "ホテル", "ビジホ", "ビジネスホテル",
            "ラブホ", "ラブホテル", "待ち合わせ",
            "派遣", "出張", "デリバリー",
            "お部屋", "お部屋番号", "号室",
        ],
        boost=12.0,
    ),
    # --- キャスト属性（タグ連動） ---
    speech.SpeechContext(
        phrases=[
            "巨乳", "貧乳", "スレンダー", "ぽっちゃり",
            "ロリ", "清楚", "ギャル", "人妻", "熟女",
            "パイパン", "色白", "小柄", "長身",
            "Eカップ", "Fカップ", "Gカップ", "Hカップ",
            "おっとり", "エロい", "積極的",
        ],
        boost=15.0,
    ),
    # --- 予約フロー用語 ---
    speech.SpeechContext(
        phrases=[
            "予約", "ご予約", "予約したい", "お願いします",
            "空いてますか", "空いてる", "案内できる",
            "出勤", "待機", "受付終了", "案内中",
            "今から", "これから", "何時から",
            "キャンセル", "変更", "確認",
        ],
        boost=10.0,
    ),
    # --- 時間表現（誤認識されやすい） ---
    speech.SpeechContext(
        phrases=[
            "1時", "2時", "3時", "4時", "5時",
            "6時", "7時", "8時", "9時", "10時",
            "11時", "12時", "1時半", "2時半", "3時半",
            "4時半", "5時半", "6時半", "7時半", "8時半",
            "9時半", "10時半", "11時半", "12時半",
            "30分後", "1時間後", "今すぐ",
        ],
        boost=8.0,
    ),
]


# ========================================
# SpeechClient管理（デリ専用）
# ========================================
class DeliSpeechClient:
    _client = None
    _lock = threading.Lock()
    _warmed_up = False

    @classmethod
    def get_client(cls):
        if cls._client is None:
            with cls._lock:
                if cls._client is None:
                    logger.info("DeliSpeechClient初期化開始...")
                    start = time.time()
                    cls._client = speech.SpeechClient(
                        client_options=ClientOptions(
                            api_endpoint="speech.googleapis.com:443"
                        )
                    )
                    elapsed = time.time() - start
                    logger.info(f"DeliSpeechClient初期化完了: {elapsed:.3f}秒")
        return cls._client

    @classmethod
    async def warmup(cls):
        if cls._warmed_up:
            return
        logger.info("=== デリASR gRPCウォームアップ開始 ===")
        start = time.time()
        client = cls.get_client()
        try:
            test_audio = b'\x00' * 3200
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=GASR_SAMPLE_RATE,
                language_code="ja-JP",
                speech_contexts=DELI_SPEECH_CONTEXTS,
            )
            audio = speech.RecognitionAudio(content=test_audio)
            client.recognize(config=config, audio=audio)
            logger.info("ウォームアップ: recognize完了（辞書付き）")
        except Exception as e:
            logger.info(f"ウォームアップ: {type(e).__name__}（接続は確立済み）")
        cls._warmed_up = True
        elapsed = time.time() - start
        logger.info(f"=== デリASRウォームアップ完了: {elapsed:.3f}秒 ===")


# ========================================
# ASRセッション（デリ専用）
# ========================================
class DeliASRSession:
    def __init__(self, session_id):
        self.session_id = session_id
        self.queue = queue.Queue()
        self.running = True
        self.first_response_logged = False
        self.session_start_time = time.time()
        self.first_audio_time = None
        self.skip_count = 5
        self.chunk_count = 0
        self.interim_responded = False
        self.mute_until = time.time() + 16  # 最初の16秒はASR結果を無視（000+001再生中）
        self.muted = True
        self.call_uuid = None  # FreeSWITCH UUID（WebSocketパスから取得）
        self.greeting_done = False  # 挨拶完了フラグ
        self.caller_number = None
        self.is_repeater = False
        self.suggest_data = None
        self.conv_state = "greeting"  # greeting → cast_confirm → course → time → location → confirm → done
        self.play_queue = asyncio.Queue()  # 再生キュー
        self.responding = False  # send_response処理中フラグ
        self.cast_name = None
        self.cast_id = None
        self.course_name = None
        self.course_minutes = None
        self.selected_time = None
        self.location = None

    async def feed_audio(self, audio_data: bytes):
        self.chunk_count += 1
        if self.first_audio_time is None:
            self.first_audio_time = time.time()
            logger.info(f"[{self.session_id}] 最初の音声チャンク受信")
        if self.chunk_count <= self.skip_count:
            if self.chunk_count == self.skip_count:
                logger.info(f"[{self.session_id}] スキップ完了、音声送信開始")
            return
        self.queue.put(audio_data)

    def _request_generator(self):
        first_chunk = True
        while True:
            chunk = self.queue.get()
            if chunk is None:
                break
            if not chunk:
                continue
            if first_chunk:
                first_chunk = False
                elapsed = time.time() - self.session_start_time
                logger.info(f"[{self.session_id}] first_chunk_yielded: {elapsed:.3f}秒")
            yield speech.StreamingRecognizeRequest(audio_content=chunk)

    async def run_recognition(self, websocket):
        logger.info(f"[{self.session_id}] デリASR認識開始")
        client = DeliSpeechClient.get_client()

        # ★ デリヘル用語辞書付き設定 ★
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=GASR_SAMPLE_RATE,
            language_code="ja-JP",
            enable_automatic_punctuation=True,
            model="default",
            speech_contexts=DELI_SPEECH_CONTEXTS,
        )

        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=True,
            single_utterance=False,
        )

        try:
            call_start = time.time()
            loop = asyncio.get_event_loop()
            resp_queue = asyncio.Queue()

            def _blocking_recognize():
                """別スレッドで streaming_recognize + イテレーション"""
                try:
                    responses = client.streaming_recognize(
                        streaming_config,
                        requests=self._request_generator()
                    )
                    elapsed = time.time() - call_start
                    logger.info(f"[{self.session_id}] streaming_recognize: {elapsed:.3f}秒")
                    for resp in responses:
                        loop.call_soon_threadsafe(resp_queue.put_nowait, resp)
                except Exception as e:
                    logger.error(f"[{self.session_id}] recognize thread error: {e}")
                finally:
                    loop.call_soon_threadsafe(resp_queue.put_nowait, None)

            # 別スレッドで実行（イベントループをブロックしない）
            loop.run_in_executor(None, _blocking_recognize)

            while True:
                response = await resp_queue.get()
                if response is None:
                    break
                if not self.first_response_logged:
                    self.first_response_logged = True
                    total = time.time() - self.session_start_time
                    logger.info(f"[{self.session_id}] 初回応答: {total:.3f}秒")

                for result in response.results:
                    transcript = result.alternatives[0].transcript
                    confidence = result.alternatives[0].confidence if result.is_final else 0
                    is_final = result.is_final

                    logger.info(
                        f"[{self.session_id}] "
                        f"{'FINAL' if is_final else 'interim'}: "
                        f"{transcript}"
                        f"{f' (conf={confidence:.2f})' if is_final else ''}"
                    )

                    # ミュート期間チェック
                    if self.muted:
                        if time.time() >= self.mute_until:
                            self.muted = False
                            logger.info(f"[{self.session_id}] ミュート解除、ASR認識開始")
                            # この結果はミュート解除後なのでそのまま処理続行
                        else:
                            continue  # 再生中は無視

                    if not is_final and len(transcript) >= 4 and not self.interim_responded:
                        self.interim_responded = True
                        asyncio.create_task(self.send_response(websocket, transcript, is_final=False))

                    if is_final:
                        # 低信頼度はノイズ（アナウンス音声の誤認識）として無視
                        if confidence < 0.25:
                            logger.info(f"[{self.session_id}] 低信頼度スキップ: {transcript} (conf={confidence:.2f})")
                            continue
                        # 再生中（send_response処理中）は無視
                        if self.responding:
                            logger.info(f"[{self.session_id}] 応答中スキップ: {transcript}")
                            continue
                        asyncio.create_task(self.send_response(websocket, transcript, is_final=True))
                        self.interim_responded = False

        except Exception as e:
            logger.error(f"[{self.session_id}] 認識エラー: {e}")

    def _esl_command(self, cmd):
        """FreeSWITCH ESL経由でコマンド実行"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect(("127.0.0.1", 8021))
            sock.recv(1024)  # auth request
            sock.sendall(b"auth ClueCon\n\n")
            sock.recv(1024)  # auth reply
            sock.sendall(f"{cmd}\n\n".encode())
            resp = sock.recv(4096).decode()
            sock.close()
            return resp
        except Exception as e:
            logger.error(f"[{self.session_id}] ESL error: {e}")
            return None

    def _esl_getvar(self, var_name):
        """FreeSWITCH ESL経由で変数取得"""
        if not self.call_uuid:
            return None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect(("127.0.0.1", 8021))
            sock.recv(1024)
            sock.sendall(b"auth ClueCon\n\n")
            sock.recv(1024)
            cmd = f"api uuid_getvar {self.call_uuid} {var_name}"
            sock.sendall(f"{cmd}\n\n".encode())
            resp = sock.recv(4096).decode()
            sock.close()
            # レスポンスからContent-Type以降の値を取得
            for line in resp.split("\n"):
                line = line.strip()
                if line and not line.startswith("Content") and line != "":
                    return line
            return None
        except Exception as e:
            logger.error(f"[{self.session_id}] ESL getvar error: {e}")
            return None

    async def _preload_caller_info(self):
        """挨拶再生中にcaller番号取得→suggest API呼び出し"""
        try:
            # 1秒待ってからESLでcaller番号取得（接続安定のため）
            loop = asyncio.get_event_loop()
            caller = await loop.run_in_executor(None, self._esl_getvar, "caller_id_number")
            if caller:
                self.caller_number = caller
                logger.info(f"[{self.session_id}] 着信番号: {caller}")
            else:
                logger.warning(f"[{self.session_id}] 着信番号取得失敗")
                return

            # suggest API呼び出し（デフォルトcourse_id + 30分後のstart_time）
            from datetime import datetime, timedelta, timezone
            jst = timezone(timedelta(hours=9))
            now = datetime.now(jst) + timedelta(minutes=30)
            now = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
            start_time = now.isoformat().replace("+", "%2B")
            default_course = "f65bf8ed-2da4-4f84-a37b-546b20e0fb93"

            url = (f"{RESERVATION_API}/api/suggest"
                   f"?tenant_id={DELI_TENANT_ID}"
                   f"&phone_number={caller}"
                   f"&course_id={default_course}"
                   f"&start_time={start_time}")

            async with aiohttp.ClientSession() as http:
                async with http.get(url) as resp:
                    if resp.status == 200:
                        self.suggest_data = await resp.json()
                        self.is_repeater = self.suggest_data.get("is_repeater", False)
                        logger.info(f"[{self.session_id}] suggest結果: repeater={self.is_repeater}, type={self.suggest_data.get('type')}")
                        if self.suggest_data.get("primary"):
                            logger.info(f"[{self.session_id}] 推しキャスト: {self.suggest_data['primary'].get('display_name')}")
                    else:
                        logger.error(f"[{self.session_id}] suggest API error: {resp.status}")
        except Exception as e:
            logger.error(f"[{self.session_id}] preload error: {e}")


    async def _create_reservation(self):
        """予約APIに予約を作成"""
        from datetime import datetime, timedelta, timezone
        jst = timezone(timedelta(hours=9))
        now = datetime.now(jst)

        # 開始時間の計算
        if self.selected_time == "最短":
            start = now + timedelta(minutes=30)
            start = start.replace(minute=(start.minute // 30) * 30, second=0, microsecond=0)
        else:
            # "18時" "18時半" などをパース
            import re
            m = re.match(r"(\d{1,2})時(半)?", self.selected_time or "")
            if m:
                hour = int(m.group(1))
                minute = 30 if m.group(2) else 0
                start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if start < now:
                    start += timedelta(days=1)
            else:
                start = now + timedelta(minutes=30)
                start = start.replace(minute=(start.minute // 30) * 30, second=0, microsecond=0)

        end = start + timedelta(minutes=self.course_minutes or 60)

        # コースID取得（suggest_dataから）
        course_id = None
        if self.suggest_data:
            # デフォルトコースID
            course_id = "f65bf8ed-2da4-4f84-a37b-546b20e0fb93"  # TODO: コース選択に応じて変更

        payload = {
            "tenant_id": DELI_TENANT_ID,
            "cast_id": self.cast_id,
            "course_id": course_id,
            "customer_phone": self.caller_number or "",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "location": self.location or "",
            "status": "confirmed",
            "notes": f"AI電話予約 session={self.session_id}"
        }

        logger.info(f"[{self.session_id}] 予約API送信: {payload}")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{RESERVATION_API}/api/reservations",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    logger.info(f"[{self.session_id}] 予約作成成功: {data.get('id', 'unknown')}")
                else:
                    text = await resp.text()
                    logger.error(f"[{self.session_id}] 予約API失敗: {resp.status} {text}")


    async def _create_reservation(self):
        """予約APIに予約を作成"""
        from datetime import datetime, timedelta, timezone
        jst = timezone(timedelta(hours=9))
        now = datetime.now(jst)

        # 開始時間の計算
        if self.selected_time == "最短":
            start = now + timedelta(minutes=30)
            start = start.replace(minute=(start.minute // 30) * 30, second=0, microsecond=0)
        else:
            # "18時" "18時半" などをパース
            import re
            m = re.match(r"(\d{1,2})時(半)?", self.selected_time or "")
            if m:
                hour = int(m.group(1))
                minute = 30 if m.group(2) else 0
                start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if start < now:
                    start += timedelta(days=1)
            else:
                start = now + timedelta(minutes=30)
                start = start.replace(minute=(start.minute // 30) * 30, second=0, microsecond=0)

        end = start + timedelta(minutes=self.course_minutes or 60)

        # コースID取得（suggest_dataから）
        course_id = None
        if self.suggest_data:
            # デフォルトコースID
            course_id = "f65bf8ed-2da4-4f84-a37b-546b20e0fb93"  # TODO: コース選択に応じて変更

        payload = {
            "tenant_id": DELI_TENANT_ID,
            "cast_id": self.cast_id,
            "course_id": course_id,
            "customer_phone": self.caller_number or "",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "location": self.location or "",
            "status": "confirmed",
            "notes": f"AI電話予約 session={self.session_id}"
        }

        logger.info(f"[{self.session_id}] 予約API送信: {payload}")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{RESERVATION_API}/api/reservations",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    logger.info(f"[{self.session_id}] 予約作成成功: {data.get('id', 'unknown')}")
                else:
                    text = await resp.text()
                    logger.error(f"[{self.session_id}] 予約API失敗: {resp.status} {text}")

    def _play_wav_sync(self, wav_path):
        """FreeSWITCH ESL sendmsg でWAV再生コマンド送信のみ（ブロックしない）"""
        if not self.call_uuid:
            logger.error(f"[{self.session_id}] UUID不明、再生不可")
            return 0
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect(("127.0.0.1", 8021))
            sock.recv(1024)
            sock.sendall(b"auth ClueCon\n\n")
            sock.recv(1024)
            msg = (
                f"sendmsg {self.call_uuid}\n"
                f"call-command: execute\n"
                f"execute-app-name: playback\n"
                f"execute-app-arg: {wav_path}\n"
                f"\n"
            )
            sock.sendall(msg.encode())
            sock.recv(4096)
            sock.close()
        except Exception as e:
            logger.error(f"[{self.session_id}] ESL再生エラー: {e}")
        return 0

    async def _play_wav(self, wav_path):
        """WAV再生 + 再生完了まで非同期待機（イベントループをブロックしない）"""
        import wave as _wave
        try:
            with _wave.open(wav_path, 'r') as wf:
                duration = wf.getnframes() / wf.getframerate()
        except:
            duration = 5.0
        self.muted = True
        self.mute_until = time.time() + duration + 0.5
        logger.info(f"[{self.session_id}] 再生: {wav_path} ({duration:.1f}秒, ミュート中)")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._play_wav_sync, wav_path)
        await asyncio.sleep(duration + 0.3)
        logger.info(f"[{self.session_id}] 再生完了")

    async def send_response(self, websocket, transcript, is_final):
        """認識結果に応じた音声応答（ステートマシン）"""
        self.responding = True
        logger.info(f"[{self.session_id}] [{self.conv_state}] 応答: {transcript} (final={is_final})")
        if not is_final:
            self.responding = False
            return

        loop = asyncio.get_event_loop()
        text = transcript.strip().replace("。", "").replace("、", "")

        # === GREETING: 最初の発話 → キャスト提案 ===
        if self.conv_state == "greeting":
            # suggest結果からキャスト情報を取得
            if self.suggest_data and self.suggest_data.get("primary"):
                self.cast_name = self.suggest_data["primary"].get("display_name")
                self.cast_id = self.suggest_data["primary"].get("cast_id")

            if self.is_repeater and self.suggest_data:
                primary = self.suggest_data.get("primary", {})
                available = primary.get("available", False)
                if available:
                    logger.info(f"[{self.session_id}] リピーター → {self.cast_name}出勤中 → 003.wav")
                    await self._play_wav( f"{AUDIO_BASE}/003.wav")
                    self.conv_state = "cast_confirm"
                else:
                    logger.info(f"[{self.session_id}] リピーター → {self.cast_name}不在 → 002.wav")
                    await self._play_wav( f"{AUDIO_BASE}/002.wav")
                    self.conv_state = "cast_confirm"
            else:
                logger.info(f"[{self.session_id}] 新規客 → 004.wav")
                await self._play_wav( f"{AUDIO_BASE}/004.wav")
                self.conv_state = "new_confirm"
            self.responding = False
            return

        # === NEW_CONFIRM: 新規客の「はい」確認 → キャスト提案 ===
        elif self.conv_state == "new_confirm":
            logger.info(f"[{self.session_id}] 新規確認応答: {text}")
            await self._play_wav( f"{AUDIO_BASE}/005.wav")
            self.conv_state = "cast_confirm"
            self.responding = False
            return

        # === CAST_CONFIRM: キャスト提案への返答 → コース確認 ===
        elif self.conv_state == "cast_confirm":
            # はい/お願い/OK系 → コース確認へ
            yes_words = ["はい", "うん", "ええ", "お願い", "それで", "いいよ", "いいです", "大丈夫", "オッケー", "OK", "おねがい"]
            if any(w in text for w in yes_words) or len(text) < 5:
                logger.info(f"[{self.session_id}] キャスト{self.cast_name}確定 → 006.wav")
                await self._play_wav( f"{AUDIO_BASE}/006.wav")
                self.conv_state = "course"
            else:
                # 別のキャスト希望 → alternativesがあれば提案
                logger.info(f"[{self.session_id}] キャスト変更希望: {text}")
                alts = self.suggest_data.get("alternatives", []) if self.suggest_data else []
                if alts:
                    self.cast_name = alts[0].get("display_name")
                    self.cast_id = alts[0].get("cast_id")
                    logger.info(f"[{self.session_id}] 代替キャスト{self.cast_name} → 005.wav")
                    await self._play_wav( f"{AUDIO_BASE}/005.wav")
                else:
                    await self._play_wav( f"{AUDIO_BASE}/006.wav")
                    self.conv_state = "course"
            self.responding = False
            return

        # === COURSE: コース選択 ===
        elif self.conv_state == "course":
            if "60" in text or "ショート" in text or "短い" in text:
                self.course_minutes = 60
                self.course_name = "60分コース"
                logger.info(f"[{self.session_id}] 60分選択 → 007.wav + 009.wav")
                await self._play_wav( f"{AUDIO_BASE}/007.wav")
                await self._play_wav( f"{AUDIO_BASE}/009.wav")
                self.conv_state = "time"
            elif "90" in text or "ロング" in text or "長い" in text:
                self.course_minutes = 90
                self.course_name = "90分コース"
                logger.info(f"[{self.session_id}] 90分選択 → 008.wav + 009.wav")
                await self._play_wav( f"{AUDIO_BASE}/008.wav")
                await self._play_wav( f"{AUDIO_BASE}/009.wav")
                self.conv_state = "time"
            else:
                logger.info(f"[{self.session_id}] コース不明: {text} → 006.wav再生")
                await self._play_wav( f"{AUDIO_BASE}/006.wav")
            self.responding = False
            return

        # === TIME: 時間確認 ===
        elif self.conv_state == "time":
            import re
            # 「今から」「すぐ」
            if any(w in text for w in ["今から", "すぐ", "最短", "できるだけ早"]):
                self.selected_time = "最短"
                logger.info(f"[{self.session_id}] 時間: 最短")
            else:
                # 「X時」「X時半」を抽出
                m = re.search(r"(\d{1,2})\s*時\s*半", text)
                if m:
                    self.selected_time = f"{int(m.group(1))}時半"
                else:
                    m = re.search(r"(\d{1,2})\s*時", text)
                    if m:
                        self.selected_time = f"{int(m.group(1))}時"

            if self.selected_time:
                logger.info(f"[{self.session_id}] 時間確定: {self.selected_time} → 011.wav")
                await self._play_wav( f"{AUDIO_BASE}/011.wav")
                self.conv_state = "location"
            else:
                logger.info(f"[{self.session_id}] 時間不明: {text} → 009.wav再生")
                await self._play_wav( f"{AUDIO_BASE}/009.wav")
            self.responding = False
            return

        # === LOCATION: 場所確認 ===
        elif self.conv_state == "location":
            if len(text) >= 2:
                self.location = text
                logger.info(f"[{self.session_id}] 場所: {self.location}")
                logger.info(f"[{self.session_id}] === 予約内容 ===")
                logger.info(f"[{self.session_id}] キャスト: {self.cast_name} ({self.cast_id})")
                logger.info(f"[{self.session_id}] コース: {self.course_name} ({self.course_minutes}分)")
                logger.info(f"[{self.session_id}] 時間: {self.selected_time}")
                logger.info(f"[{self.session_id}] 場所: {self.location}")
                logger.info(f"[{self.session_id}] 電話番号: {self.caller_number}")

                # === 予約APIに登録 ===
                try:
                    await self._create_reservation()
                    logger.info(f"[{self.session_id}] 予約API登録完了")
                except Exception as e:
                    logger.error(f"[{self.session_id}] 予約API登録エラー: {e}")

                logger.info(f"[{self.session_id}] 予約確定 → 010.wav")
                await self._play_wav( f"{AUDIO_BASE}/010.wav")
                self.conv_state = "done"
            self.responding = False
            return

        # === CONFIRM: 最終確認 ===
        elif self.conv_state == "confirm":
            yes_words = ["はい", "うん", "お願い", "それで", "いいよ", "大丈夫", "OK"]
            if any(w in text for w in yes_words):
                logger.info(f"[{self.session_id}] 予約確定!")
                await self._play_wav( f"{AUDIO_BASE}/010.wav")
                self.conv_state = "done"
            self.responding = False
            return

        self.responding = False
    def stop(self):
        self.running = False
        self.queue.put(None)


# ========================================
# WebSocketハンドラ
# ========================================
async def handle_websocket(websocket):
    session_id = f"deli_{int(time.time()*1000)}"
    logger.info(f"[{session_id}] デリASR接続開始: {websocket.request.path}")

    session = DeliASRSession(session_id)
    # WebSocketパスからFreeSWITCH UUIDを取得
    ws_path = websocket.request.path
    session.call_uuid = ws_path.strip("/") if ws_path else None
    logger.info(f"[{session_id}] FreeSWITCH UUID: {session.call_uuid}")
    recognition_task = asyncio.create_task(session.run_recognition(websocket))
    preload_task = asyncio.create_task(session._preload_caller_info())

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                await session.feed_audio(message)
            else:
                logger.info(f"[{session_id}] テキスト: {message}")
    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"[{session_id}] 接続クローズ: {e}")
    finally:
        session.stop()
        recognition_task.cancel()
        try:
            await recognition_task
        except asyncio.CancelledError:
            pass
        logger.info(f"[{session_id}] セッション終了")


async def main():
    logger.info("=== デリヘル専用ASR Server 起動 ===")
    await DeliSpeechClient.warmup()

    async def periodic_warmup():
        while True:
            await asyncio.sleep(300)
            await DeliSpeechClient.warmup()

    asyncio.create_task(periodic_warmup())

    async with websockets.serve(handle_websocket, "0.0.0.0", WS_PORT):
        logger.info(f"デリASR WebSocket: port {WS_PORT}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
