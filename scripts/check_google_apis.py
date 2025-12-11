#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Cloud API診断スクリプト

LibertyCall プロジェクトで使用している Google Cloud API の接続状態を診断します。

対象API:
- Cloud Text-to-Speech（正常）
- Cloud Speech-to-Text（全エラー）
- Generative Language API（単発エラー）

使い方:
    python scripts/check_google_apis.py

環境変数:
    GOOGLE_APPLICATION_CREDENTIALS: サービスアカウントキーのパス
    GEMINI_API_KEY: Generative Language API の API キー
    LC_GOOGLE_PROJECT_ID: Google Cloud プロジェクトID（オプション、デフォルト: libertycall-main）
"""

import os
import sys
import json
import wave
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from google.cloud import speech_v1p1beta1 as speech
    from google.cloud import texttospeech
    from google.auth import default
    from google.auth.exceptions import DefaultCredentialsError
    GOOGLE_CLOUD_AVAILABLE = True
except ImportError:
    GOOGLE_CLOUD_AVAILABLE = False
    speech = None
    texttospeech = None
    default = None
    DefaultCredentialsError = Exception

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from tabulate import tabulate
    TABULATE_AVAILABLE = True
except ImportError:
    TABULATE_AVAILABLE = False


# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_AUDIO_PATH = PROJECT_ROOT / "test_audio.wav"
DEFAULT_CREDENTIALS_PATHS = [
    "/opt/libertycall/key/google_tts.json",
    "/opt/libertycall/key/libertycall-main-7e4af202cdff.json",
]


@dataclass
class DiagnosticResult:
    """診断結果を格納するデータクラス"""
    name: str
    status: str  # "success", "error", "warning"
    message: str
    details: Optional[str] = None
    suggestions: list = None
    
    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


class GoogleAPIDiagnostics:
    """Google Cloud API診断クラス"""
    
    def __init__(self):
        self.results: list[DiagnosticResult] = []
        self.credentials_path: Optional[str] = None
        self.project_id: Optional[str] = None
        self.gemini_api_key: Optional[str] = None
        
    def check_credentials(self) -> DiagnosticResult:
        """
        認証情報の確認
        
        Returns:
            DiagnosticResult: 診断結果
        """
        print("🔍 認証情報を確認中...")
        
        # 環境変数から認証情報パスを取得
        creds_paths = []
        
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            creds_paths.append(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
        
        if os.getenv("LC_GOOGLE_CREDENTIALS_PATH"):
            creds_paths.append(os.getenv("LC_GOOGLE_CREDENTIALS_PATH"))
        
        # デフォルトパスも確認
        for default_path in DEFAULT_CREDENTIALS_PATHS:
            if os.path.exists(default_path):
                creds_paths.append(default_path)
        
        # 存在する認証ファイルを探す
        self.credentials_path = None
        for path in creds_paths:
            if path and os.path.exists(path):
                self.credentials_path = path
                break
        
        if not self.credentials_path:
            return DiagnosticResult(
                name="認証",
                status="error",
                message="❌ 認証ファイルが見つかりません",
                details="GOOGLE_APPLICATION_CREDENTIALS 環境変数が設定されていないか、ファイルが存在しません",
                suggestions=[
                    "GOOGLE_APPLICATION_CREDENTIALS 環境変数を設定してください",
                    "サービスアカウントキーJSONファイルのパスを確認してください",
                    "デフォルトパス (/opt/libertycall/key/google_tts.json) にファイルを配置してください"
                ]
            )
        
        # 認証ファイルの内容を確認
        try:
            with open(self.credentials_path, "r", encoding="utf-8") as f:
                creds_data = json.load(f)
            
            # プロジェクトIDを取得
            self.project_id = creds_data.get("project_id") or os.getenv("LC_GOOGLE_PROJECT_ID") or "libertycall-main"
            
            # 認証情報の有効性を確認
            try:
                if GOOGLE_CLOUD_AVAILABLE:
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path
                    credentials, project = default()
                    if project:
                        self.project_id = project
            except DefaultCredentialsError as e:
                return DiagnosticResult(
                    name="認証",
                    status="error",
                    message="❌ 認証情報が無効です",
                    details=str(e),
                    suggestions=[
                        "サービスアカウントキーが正しいか確認してください",
                        "キーが期限切れでないか確認してください",
                        "必要なAPIが有効化されているか確認してください"
                    ]
                )
            
            return DiagnosticResult(
                name="認証",
                status="success",
                message=f"✅ 認証OK: プロジェクト {self.project_id}",
                details=f"認証ファイル: {self.credentials_path}"
            )
            
        except json.JSONDecodeError:
            return DiagnosticResult(
                name="認証",
                status="error",
                message="❌ 認証ファイルの形式が不正です",
                details="JSON形式のファイルである必要があります",
                suggestions=[
                    "認証ファイルが正しいJSON形式か確認してください",
                    "ファイルが破損していないか確認してください"
                ]
            )
        except Exception as e:
            return DiagnosticResult(
                name="認証",
                status="error",
                message=f"❌ 認証ファイルの読み込みに失敗しました: {e}",
                suggestions=[
                    "ファイルの読み取り権限を確認してください",
                    "ファイルパスが正しいか確認してください"
                ]
            )
    
    def check_stt_status(self) -> DiagnosticResult:
        """
        Speech-to-Text の接続テスト
        
        Returns:
            DiagnosticResult: 診断結果
        """
        print("🔍 Speech-to-Text を確認中...")
        
        if not GOOGLE_CLOUD_AVAILABLE:
            return DiagnosticResult(
                name="Speech-to-Text",
                status="error",
                message="❌ google-cloud-speech パッケージがインストールされていません",
                suggestions=[
                    "pip install google-cloud-speech を実行してください"
                ]
            )
        
        if not self.credentials_path:
            return DiagnosticResult(
                name="Speech-to-Text",
                status="error",
                message="❌ 認証情報が設定されていません",
                suggestions=[
                    "先に認証情報を確認してください"
                ]
            )
        
        # テスト音声ファイルを探す
        test_audio = None
        test_audio_candidates = [
            TEST_AUDIO_PATH,
            PROJECT_ROOT / "sample_audio.wav",
            PROJECT_ROOT / "test_output_audio.wav",
            PROJECT_ROOT / "tts_test" / "004_moshimoshi.wav",
            PROJECT_ROOT / "data" / "sample_audio.wav",
        ]
        
        for candidate in test_audio_candidates:
            if candidate.exists():
                test_audio = candidate
                break
        
        # テスト音声ファイルが存在しない場合は、簡単なテスト音声を生成
        if not test_audio:
            test_audio = self._create_test_audio()
        
        if not test_audio or not test_audio.exists():
            return DiagnosticResult(
                name="Speech-to-Text",
                status="error",
                message="❌ テスト音声ファイルが見つかりません",
                suggestions=[
                    "test_audio.wav を作成してください",
                    "または既存の音声ファイルを test_audio.wav として配置してください"
                ]
            )
        
        try:
            # 音声ファイルの形式を確認
            audio_format = self.check_audio_format(test_audio)
            
            # Speech-to-Text クライアントを初期化
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path
            client = speech.SpeechClient()
            
            # 音声ファイルを読み込む
            with open(test_audio, "rb") as audio_file:
                audio_content = audio_file.read()
            
            # 認識設定
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code="ja-JP",
                use_enhanced=True,
                audio_channel_count=1,
            )
            
            # 認識リクエスト
            audio = speech.RecognitionAudio(content=audio_content)
            response = client.recognize(config=config, audio=audio)
            
            # 結果を取得
            if response.results:
                transcript = response.results[0].alternatives[0].transcript
                return DiagnosticResult(
                    name="Speech-to-Text",
                    status="success",
                    message=f"✅ Speech-to-Text: 成功（認識結果: 「{transcript}」）",
                    details=f"音声形式: {audio_format}"
                )
            else:
                return DiagnosticResult(
                    name="Speech-to-Text",
                    status="warning",
                    message="⚠️ Speech-to-Text: 認識結果が空です",
                    details="音声ファイルが無音か、認識できない内容の可能性があります",
                    suggestions=[
                        "音声ファイルに実際の音声が含まれているか確認してください",
                        "音声の音量が十分か確認してください"
                    ]
                )
                
        except Exception as e:
            error_msg = str(e)
            error_code = None
            
            # エラーコードを抽出
            if "INVALID_ARGUMENT" in error_msg:
                error_code = "INVALID_ARGUMENT"
            elif "PERMISSION_DENIED" in error_msg:
                error_code = "PERMISSION_DENIED"
            elif "UNAUTHENTICATED" in error_msg:
                error_code = "UNAUTHENTICATED"
            elif "NOT_FOUND" in error_msg:
                error_code = "NOT_FOUND"
            
            suggestions = []
            if error_code == "INVALID_ARGUMENT":
                suggestions = [
                    "音声エンコーディングがμ-lawの可能性（LINEAR16/PCM形式が必要）",
                    "サンプリングレートが16000Hzでない可能性",
                    "音声チャンネル数が1（モノラル）でない可能性"
                ]
            elif error_code == "PERMISSION_DENIED":
                suggestions = [
                    "サービスアカウントの権限不足",
                    "Cloud Speech-to-Text API が有効化されていない可能性",
                    "プロジェクトIDが正しいか確認してください"
                ]
            elif error_code == "UNAUTHENTICATED":
                suggestions = [
                    "認証情報が無効です",
                    "サービスアカウントキーが期限切れの可能性",
                    "GOOGLE_APPLICATION_CREDENTIALS 環境変数を再設定してください"
                ]
            elif error_code == "NOT_FOUND":
                suggestions = [
                    "プロジェクトが見つかりません",
                    "プロジェクトIDが正しいか確認してください"
                ]
            else:
                suggestions = [
                    "エラーメッセージを確認してください",
                    "Google Cloud Console で API の状態を確認してください",
                    "ネットワーク接続を確認してください"
                ]
            
            return DiagnosticResult(
                name="Speech-to-Text",
                status="error",
                message=f"❌ Speech-to-Text: {error_code or 'エラー'}",
                details=error_msg,
                suggestions=suggestions
            )
    
    def check_gemini_status(self) -> DiagnosticResult:
        """
        Generative Language API (Gemini) の疎通確認
        
        Returns:
            DiagnosticResult: 診断結果
        """
        print("🔍 Gemini API を確認中...")
        
        if not REQUESTS_AVAILABLE:
            return DiagnosticResult(
                name="Gemini API",
                status="error",
                message="❌ requests パッケージがインストールされていません",
                suggestions=[
                    "pip install requests を実行してください"
                ]
            )
        
        # API キーを取得
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        
        if not self.gemini_api_key:
            return DiagnosticResult(
                name="Gemini API",
                status="error",
                message="❌ GEMINI_API_KEY 環境変数が設定されていません",
                suggestions=[
                    ".env ファイルに GEMINI_API_KEY=your_api_key_here を追加してください",
                    "または環境変数として設定してください: export GEMINI_API_KEY=your_api_key_here"
                ]
            )
        
        try:
            # Gemini API のテストリクエスト
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"
            headers = {
                "Content-Type": "application/json",
            }
            params = {
                "key": self.gemini_api_key
            }
            data = {
                "contents": [{
                    "parts": [{
                        "text": "こんにちは"
                    }]
                }]
            }
            
            response = requests.post(url, headers=headers, params=params, json=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if "candidates" in result and len(result["candidates"]) > 0:
                    reply = result["candidates"][0]["content"]["parts"][0]["text"]
                    return DiagnosticResult(
                        name="Gemini API",
                        status="success",
                        message=f"✅ Gemini API: 成功（応答: \"{reply[:50]}...\"）",
                        details="Generative Language API への接続が正常です"
                    )
                else:
                    return DiagnosticResult(
                        name="Gemini API",
                        status="warning",
                        message="⚠️ Gemini API: 応答が空です",
                        details="API は接続できましたが、応答が空でした"
                    )
            elif response.status_code == 400:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", "Bad Request")
                return DiagnosticResult(
                    name="Gemini API",
                    status="error",
                    message="❌ Gemini API: リクエストエラー",
                    details=error_msg,
                    suggestions=[
                        "API キーが正しいか確認してください",
                        "リクエスト形式が正しいか確認してください"
                    ]
                )
            elif response.status_code == 401:
                return DiagnosticResult(
                    name="Gemini API",
                    status="error",
                    message="❌ Gemini API: 認証エラー",
                    details="API キーが無効です",
                    suggestions=[
                        "API キーが正しいか確認してください",
                        "API キーが期限切れでないか確認してください",
                        "Google Cloud Console で API キーを再発行してください"
                    ]
                )
            elif response.status_code == 403:
                return DiagnosticResult(
                    name="Gemini API",
                    status="error",
                    message="❌ Gemini API: 権限エラー",
                    details="API が有効化されていないか、権限が不足しています",
                    suggestions=[
                        "Generative Language API が有効化されているか確認してください",
                        "API キーに適切な権限が設定されているか確認してください"
                    ]
                )
            else:
                return DiagnosticResult(
                    name="Gemini API",
                    status="error",
                    message=f"❌ Gemini API: HTTP {response.status_code}",
                    details=response.text[:200],
                    suggestions=[
                        "Google Cloud Console で API の状態を確認してください",
                        "ネットワーク接続を確認してください"
                    ]
                )
                
        except requests.exceptions.Timeout:
            return DiagnosticResult(
                name="Gemini API",
                status="error",
                message="❌ Gemini API: タイムアウト",
                details="API への接続がタイムアウトしました",
                suggestions=[
                    "ネットワーク接続を確認してください",
                    "ファイアウォール設定を確認してください"
                ]
            )
        except requests.exceptions.RequestException as e:
            return DiagnosticResult(
                name="Gemini API",
                status="error",
                message=f"❌ Gemini API: 接続エラー",
                details=str(e),
                suggestions=[
                    "ネットワーク接続を確認してください",
                    "API エンドポイントが正しいか確認してください"
                ]
            )
        except Exception as e:
            return DiagnosticResult(
                name="Gemini API",
                status="error",
                message=f"❌ Gemini API: 予期しないエラー",
                details=str(e),
                suggestions=[
                    "エラーメッセージを確認してください",
                    "Google Cloud Console で API の状態を確認してください"
                ]
            )
    
    def check_audio_format(self, audio_path: Path) -> str:
        """
        音声ファイル形式の自動判定
        
        Args:
            audio_path: 音声ファイルのパス
            
        Returns:
            str: 音声形式の説明（例: "1ch 16000Hz 16bit"）
        """
        try:
            with wave.open(str(audio_path), "rb") as wf:
                channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                sample_width = wf.getsampwidth()
                
                # エンコーディング形式を判定
                if sample_width == 1:
                    encoding = "8bit"
                elif sample_width == 2:
                    encoding = "16bit"
                elif sample_width == 4:
                    encoding = "32bit"
                else:
                    encoding = f"{sample_width * 8}bit"
                
                return f"{channels}ch {sample_rate}Hz {encoding}"
        except Exception as e:
            return f"形式判定失敗: {e}"
    
    def _create_test_audio(self) -> Optional[Path]:
        """
        簡単なテスト音声ファイルを生成
        
        Returns:
            Optional[Path]: 生成された音声ファイルのパス
        """
        try:
            if not GOOGLE_CLOUD_AVAILABLE or not texttospeech:
                return None
            
            if not self.credentials_path:
                return None
            
            print("📝 テスト音声ファイルを生成中...")
            
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path
            client = texttospeech.TextToSpeechClient()
            
            synthesis_input = texttospeech.SynthesisInput(text="もしもし")
            voice = texttospeech.VoiceSelectionParams(
                language_code="ja-JP",
                name="ja-JP-Neural2-B",
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
            )
            
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            
            # WAVファイルとして保存
            test_audio = TEST_AUDIO_PATH
            test_audio.parent.mkdir(parents=True, exist_ok=True)
            
            with wave.open(str(test_audio), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(response.audio_content)
            
            return test_audio
            
        except Exception as e:
            print(f"⚠️ テスト音声ファイルの生成に失敗しました: {e}")
            return None
    
    def print_summary(self):
        """診断結果を表形式で表示"""
        print("\n" + "=" * 80)
        print("Google Cloud API 診断結果")
        print("=" * 80)
        
        if TABULATE_AVAILABLE:
            table_data = []
            for result in self.results:
                status_icon = "✅" if result.status == "success" else "❌" if result.status == "error" else "⚠️"
                table_data.append([
                    result.name,
                    f"{status_icon} {result.message}",
                    result.details or "-"
                ])
            
            print(tabulate(table_data, headers=["検査項目", "結果", "詳細"], tablefmt="grid"))
        else:
            for result in self.results:
                print(f"\n【{result.name}】")
                print(f"  結果: {result.message}")
                if result.details:
                    print(f"  詳細: {result.details}")
                if result.suggestions:
                    print("  原因候補:")
                    for i, suggestion in enumerate(result.suggestions, 1):
                        print(f"    {i}. {suggestion}")
        
        print("\n" + "=" * 80)
        
        # 全体の状態を判定
        success_count = sum(1 for r in self.results if r.status == "success")
        error_count = sum(1 for r in self.results if r.status == "error")
        warning_count = sum(1 for r in self.results if r.status == "warning")
        
        if error_count == 0 and warning_count == 0:
            print("✅ 全て正常です。Google API設定は完了しています。")
        elif error_count > 0:
            print(f"❌ {error_count}個のエラーが見つかりました。上記の原因候補を確認してください。")
        else:
            print(f"⚠️ {warning_count}個の警告があります。")
        
        print("=" * 80)
        
        # .env ファイルの設定例を表示
        if error_count > 0:
            print("\n📝 .env ファイルの設定例:")
            print("-" * 80)
            print("# Google Cloud API 認証設定")
            print("GOOGLE_APPLICATION_CREDENTIALS=/opt/libertycall/key/google_tts.json")
            print("")
            print("# または、LibertyCall専用の環境変数を使用")
            print("LC_GOOGLE_CREDENTIALS_PATH=/opt/libertycall/key/google_tts.json")
            print("")
            print("# Google Cloud プロジェクトID（オプション、デフォルト: libertycall-main）")
            print("LC_GOOGLE_PROJECT_ID=libertycall-main")
            print("")
            print("# Generative Language API (Gemini) の API キー")
            print("# Google Cloud Console で API キーを発行して設定してください")
            print("GEMINI_API_KEY=your_api_key_here")
            print("-" * 80)


def main():
    """メイン処理"""
    print("=" * 80)
    print("Google Cloud API 診断スクリプト")
    print("=" * 80)
    print()
    
    # 依存パッケージの確認
    if not GOOGLE_CLOUD_AVAILABLE:
        print("❌ エラー: google-cloud-speech または google-cloud-texttospeech がインストールされていません")
        print("   pip install google-cloud-speech google-cloud-texttospeech を実行してください")
        return 1
    
    if not REQUESTS_AVAILABLE:
        print("❌ エラー: requests パッケージがインストールされていません")
        print("   pip install requests を実行してください")
        return 1
    
    # 診断を実行
    diagnostics = GoogleAPIDiagnostics()
    
    # 1. 認証確認
    result = diagnostics.check_credentials()
    diagnostics.results.append(result)
    
    # 2. Speech-to-Text 確認
    result = diagnostics.check_stt_status()
    diagnostics.results.append(result)
    
    # 3. Gemini API 確認
    result = diagnostics.check_gemini_status()
    diagnostics.results.append(result)
    
    # 4. 音声フォーマット確認（テスト音声ファイルがある場合）
    test_audio = TEST_AUDIO_PATH
    if not test_audio.exists():
        for candidate in [
            PROJECT_ROOT / "sample_audio.wav",
            PROJECT_ROOT / "test_output_audio.wav",
            PROJECT_ROOT / "tts_test" / "004_moshimoshi.wav",
        ]:
            if candidate.exists():
                test_audio = candidate
                break
    
    if test_audio.exists():
        audio_format = diagnostics.check_audio_format(test_audio)
        diagnostics.results.append(DiagnosticResult(
            name="音声フォーマット",
            status="success",
            message=f"✅ 音声フォーマット: {audio_format}",
            details=f"ファイル: {test_audio}"
        ))
    
    # 結果を表示
    diagnostics.print_summary()
    
    # エラーがある場合は終了コード1を返す
    error_count = sum(1 for r in diagnostics.results if r.status == "error")
    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
