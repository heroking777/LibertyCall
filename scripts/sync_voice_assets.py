#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
クライアント000の音声ファイルと音声リストの不一致を自動修正するスクリプト

機能:
- intent_rules.py の TEMPLATE_CONFIG と voice_lines_000.json を比較
- テキスト不一致を検出・修正
- 不足音声ファイルをリストアップ
- 不要な音声ファイルを削除（オプション）
"""

import json
import sys
import shutil
import argparse
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Set, Tuple, Optional, List
import logging

PROJECT_ROOT = Path("/opt/libertycall")
sys.path.insert(0, str(PROJECT_ROOT))

from libertycall.gateway.intent_rules import TEMPLATE_CONFIG

# ログ設定（結果が見えない環境向けにDEBUGで出力）
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Google Cloud Speech-to-Text のインポート（オプション）
try:
    from google.cloud import speech
    SPEECH_AVAILABLE = True
except ImportError:
    SPEECH_AVAILABLE = False

# 文字列類似度計算のインポート（オプション）
try:
    from fuzzywuzzy import fuzz
    FUZZYWUZZY_AVAILABLE = True
except ImportError:
    try:
        from difflib import SequenceMatcher
        FUZZYWUZZY_AVAILABLE = False
    except ImportError:
        FUZZYWUZZY_AVAILABLE = False

# パス定義
VOICE_LINES_PATH = PROJECT_ROOT / "clients" / "000" / "config" / "voice_lines_000.json"
AUDIO_DIR = PROJECT_ROOT / "clients" / "000" / "audio"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "audio_sync_report.txt"

# ログディレクトリを作成
LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_voice_lines() -> Dict:
    """voice_lines_000.json を読み込む"""
    if not VOICE_LINES_PATH.exists():
        print(f"❌ エラー: {VOICE_LINES_PATH} が見つかりません")
        sys.exit(1)
    
    with open(VOICE_LINES_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def backup_voice_lines() -> Path:
    """voice_lines_000.json のバックアップを作成"""
    backup_path = VOICE_LINES_PATH.with_suffix('.json.bak')
    shutil.copy2(VOICE_LINES_PATH, backup_path)
    print(f"✅ バックアップ作成: {backup_path}")
    return backup_path


def get_audio_files() -> Set[str]:
    """音声ファイルのテンプレートIDを取得"""
    audio_files = set()
    if AUDIO_DIR.exists():
        for wav_file in AUDIO_DIR.glob("*.wav"):
            template_id = wav_file.stem.replace("template_", "")
            audio_files.add(template_id)
    return audio_files


def calculate_similarity(text1: str, text2: str) -> float:
    """2つのテキストの類似度を計算（0.0-1.0）"""
    if not text1 or not text2:
        return 0.0
    
    # 正規化（空白削除、小文字化）
    text1_norm = text1.strip().replace(" ", "").replace("　", "")
    text2_norm = text2.strip().replace(" ", "").replace("　", "")
    
    if not text1_norm or not text2_norm:
        return 0.0
    
    if FUZZYWUZZY_AVAILABLE:
        # fuzzywuzzy を使用
        ratio = fuzz.ratio(text1_norm, text2_norm) / 100.0
        return ratio
    else:
        # difflib を使用
        from difflib import SequenceMatcher
        return SequenceMatcher(None, text1_norm, text2_norm).ratio()


def transcribe_audio(wav_path: Path) -> Optional[str]:
    """Google Cloud Speech-to-Text を使用して音声を文字起こし"""
    if not SPEECH_AVAILABLE:
        return None
    
    try:
        # 認証情報の設定
        cred_path = PROJECT_ROOT / "key" / "google_tts.json"
        if cred_path.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_path)
        
        client = speech.SpeechClient()
        
        # 音声ファイルを読み込み
        with open(wav_path, "rb") as audio_file:
            content = audio_file.read()
        
        # 音声認識設定
        # WAVファイルの形式を確認（LINEAR16, 24000Hz, 1ch を想定）
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=24000,
            language_code="ja-JP",
            audio_channel_count=1,
        )
        
        audio = speech.RecognitionAudio(content=content)
        
        # 音声認識実行
        response = client.recognize(config=config, audio=audio)
        
        # 結果を結合
        transcripts = []
        for result in response.results:
            transcripts.append(result.alternatives[0].transcript)
        
        return " ".join(transcripts) if transcripts else None
        
    except Exception as e:
        print(f"  ⚠️ 音声認識エラー ({wav_path.name}): {e}")
        return None


def regenerate_tts(template_id: str, config: Dict) -> bool:
    """テンプレートからTTSを再生成してWAVを上書き"""
    try:
        from google.cloud import texttospeech  # type: ignore
    except ImportError:
        print("⚠️ google-cloud-texttospeech が未インストールのため再生成をスキップしました。")
        return False
    
    text = config.get("text", "").strip()
    if not text:
        print(f"⚠️ テンプレート {template_id} に text がありません。再生成をスキップします。")
        return False
    
    voice_name = config.get("voice", "ja-JP-Neural2-B")
    rate = float(config.get("rate", 1.1))
    
    cred_file = PROJECT_ROOT / "key" / "google_tts.json"
    if cred_file.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_file)
    
    try:
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="ja-JP",
            name=voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=24000,
            speaking_rate=rate,
        )
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        output_path = AUDIO_DIR / f"template_{template_id}.wav"
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(response.audio_content)
        
        print(f"✅ 再TTS生成完了: template_{template_id}.wav")
        return True
    except Exception as e:
        print(f"⚠️ 再TTS生成に失敗しました (template_{template_id}): {e}")
        return False


def verify_audio_content(
    template_config: Dict,
    audio_files: Set[str],
    similarity_threshold: float = 0.8
) -> List[Tuple[str, str, str, float]]:
    """音声ファイルの内容を検証"""
    mismatches = []
    
    if not SPEECH_AVAILABLE:
        print("⚠️ Google Cloud Speech-to-Text が利用できません。")
        print("   pip install google-cloud-speech を実行してください。")
        return mismatches
    
    print("\n🎤 音声内容検証中...")
    
    checked_count = 0
    for template_id in sorted(audio_files):
        if template_id not in template_config:
            continue
        
        expected_text = template_config.get(template_id, {}).get('text', '').strip()
        if not expected_text:
            continue
        
        wav_path = AUDIO_DIR / f"template_{template_id}.wav"
        if not wav_path.exists():
            continue
        
        checked_count += 1
        print(f"  [{checked_count}] template_{template_id}.wav を検証中...", end="", flush=True)
        
        # 音声を文字起こし
        detected_text = transcribe_audio(wav_path)
        
        if detected_text is None:
            print(" ❌ (認識失敗)")
            logging.warning(f"STT failed for {wav_path.name}")
            continue
        
        # 類似度を計算
        similarity = calculate_similarity(expected_text, detected_text)
        
        if similarity < similarity_threshold:
            print(f" ⚠️ (一致率: {similarity:.2f}) -> 再TTS生成を試行します")
            regen_ok = regenerate_tts(template_id, template_config.get(template_id, {}))
            if regen_ok:
                # 再度文字起こしして類似度を再計算
                new_detected = transcribe_audio(wav_path)
                if new_detected:
                    new_similarity = calculate_similarity(expected_text, new_detected)
                    if new_similarity >= similarity_threshold:
                        print(f"   ✅ 再生成後の一致率: {new_similarity:.2f} (しきい値達成)")
                        logging.info(
                            f"[AUDIO_REGEN_OK] tpl={template_id} similarity={new_similarity:.2f} (>= {similarity_threshold})"
                        )
                        continue
                    else:
                        print(f"   ⚠️ 再生成後も一致率低: {new_similarity:.2f}")
                        logging.warning(
                            f"[AUDIO_REGEN_LOW] tpl={template_id} similarity={new_similarity:.2f} (< {similarity_threshold})"
                        )
                        mismatches.append((template_id, expected_text, new_detected, new_similarity))
                        continue
            mismatches.append((template_id, expected_text, detected_text, similarity))
            logging.warning(
                f"[AUDIO_MISMATCH] tpl={template_id} similarity={similarity:.2f} (< {similarity_threshold})"
            )
        else:
            print(f" ✅ (一致率: {similarity:.2f})")
    
    return mismatches


def find_mismatches(template_config: Dict, voice_lines: Dict) -> Dict[str, Tuple[str, str]]:
    """テキスト不一致を検出"""
    mismatches = {}
    voice_template_ids = {k for k in voice_lines.keys() if k != 'voice'}
    common_ids = set(template_config.keys()) & voice_template_ids
    
    for tid in common_ids:
        template_text = template_config.get(tid, {}).get('text', '').strip()
        voice_text = voice_lines.get(tid, {}).get('text', '').strip()
        
        if template_text != voice_text:
            mismatches[tid] = (voice_text, template_text)
    
    return mismatches


def update_voice_lines(template_config: Dict, voice_lines: Dict) -> Dict:
    """voice_lines_000.json を intent_rules.py の内容で更新"""
    updated = voice_lines.copy()
    
    # intent_rules.py の全テンプレートを反映
    for tid, config in template_config.items():
        # 既存のエントリを更新、または新規追加
        if tid in updated:
            # 既存のエントリを保持しつつ、テキストとrateを更新
            updated[tid]['text'] = config.get('text', updated[tid].get('text', ''))
            updated[tid]['voice'] = config.get('voice', updated[tid].get('voice', 'ja-JP-Neural2-B'))
            updated[tid]['rate'] = config.get('rate', updated[tid].get('rate', 1.1))
        else:
            # 新規追加
            updated[tid] = {
                'text': config.get('text', ''),
                'voice': config.get('voice', 'ja-JP-Neural2-B'),
                'rate': config.get('rate', 1.1)
            }
    
    # intent_rules.py に存在しないテンプレートを削除（voiceキーは保持）
    template_ids = set(template_config.keys())
    to_remove = [tid for tid in updated.keys() if tid not in template_ids and tid != 'voice']
    for tid in to_remove:
        del updated[tid]
    
    return updated


def save_voice_lines(voice_lines: Dict) -> None:
    """voice_lines_000.json を保存"""
    with open(VOICE_LINES_PATH, 'w', encoding='utf-8') as f:
        json.dump(voice_lines, f, ensure_ascii=False, indent=2)
    print(f"✅ 更新完了: {VOICE_LINES_PATH}")


def generate_report(
    template_config: Dict,
    voice_lines: Dict,
    audio_files: Set[str],
    mismatches: Dict[str, Tuple[str, str]],
    missing_audio: Set[str],
    orphan_audio: Set[str],
    updated: bool,
    audio_mismatches: Optional[List[Tuple[str, str, str, float]]] = None
) -> str:
    """レポートを生成"""
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("クライアント000 音声アセット同期レポート")
    report_lines.append("=" * 80)
    report_lines.append(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")
    
    # 統計情報
    template_ids = set(template_config.keys())
    voice_ids = {k for k in voice_lines.keys() if k != 'voice'}
    common_ids = template_ids & voice_ids
    only_in_template = template_ids - voice_ids
    only_in_voice = voice_ids - template_ids
    
    report_lines.append("📊 統計情報:")
    report_lines.append(f"  - intent_rules.py テンプレート数: {len(template_ids)}")
    report_lines.append(f"  - voice_lines_000.json テンプレート数: {len(voice_ids)}")
    report_lines.append(f"  - 共通テンプレート: {len(common_ids)}")
    report_lines.append(f"  - 音声ファイル数: {len(audio_files)}")
    report_lines.append("")
    
    # テキスト不一致
    if mismatches:
        report_lines.append(f"⚠️ テキスト不一致 ({len(mismatches)}件):")
        for tid in sorted(mismatches.keys()):
            old_text, new_text = mismatches[tid]
            report_lines.append(f"  - テンプレート {tid}:")
            report_lines.append(f"    旧: {old_text}")
            report_lines.append(f"    新: {new_text}")
        report_lines.append("")
    else:
        report_lines.append("✅ テキスト不一致なし")
        report_lines.append("")
    
    # intent_rules.py のみに存在
    if only_in_template:
        report_lines.append(f"➕ intent_rules.py のみに存在 ({len(only_in_template)}件):")
        for tid in sorted(only_in_template):
            text = template_config.get(tid, {}).get('text', 'N/A')
            report_lines.append(f"  - {tid}: {text[:70]}...")
        report_lines.append("")
    
    # voice_lines_000.json のみに存在（削除対象）
    if only_in_voice:
        report_lines.append(f"➖ voice_lines_000.json のみに存在（削除対象） ({len(only_in_voice)}件):")
        for tid in sorted(only_in_voice):
            if tid == 'voice':
                continue
            text = voice_lines.get(tid, {}).get('text', 'N/A')
            report_lines.append(f"  - {tid}: {text[:70]}...")
        report_lines.append("")
    
    # 不足音声ファイル
    if missing_audio:
        report_lines.append(f"⚠️ 不足音声ファイル ({len(missing_audio)}件):")
        for tid in sorted(missing_audio):
            text = template_config.get(tid, {}).get('text', 'N/A')
            report_lines.append(f"  - template_{tid}.wav: {text[:70]}...")
        report_lines.append("")
    else:
        report_lines.append("✅ すべてのテンプレートに対応する音声ファイルが存在します")
        report_lines.append("")
    
    # 孤立音声ファイル
    if orphan_audio:
        report_lines.append(f"⚠️ 孤立音声ファイル（intent_rules.pyに存在しない） ({len(orphan_audio)}件):")
        for tid in sorted(orphan_audio):
            report_lines.append(f"  - template_{tid}.wav")
        report_lines.append("")
    
    # 音声内容不一致
    if audio_mismatches:
        report_lines.append(f"🎤 [AUDIO_CHECK]")
        report_lines.append(f"  - Checked {len(audio_files)} audio files")
        report_lines.append(f"  - Mismatched content: {len(audio_mismatches)}件")
        report_lines.append("")
        for tid, expected, detected, similarity in audio_mismatches:
            report_lines.append(f"  [AUDIO_MISMATCH] template_{tid}.wav")
            report_lines.append(f"    expected: {expected}")
            report_lines.append(f"    detected: {detected}")
            report_lines.append(f"    similarity: {similarity:.2f}")
            report_lines.append("")
    elif audio_mismatches is not None:
        report_lines.append(f"🎤 [AUDIO_CHECK]")
        report_lines.append(f"  - Checked {len(audio_files)} audio files")
        report_lines.append(f"  - All audio content matches ✅")
        report_lines.append("")
    
    # 更新状況
    if updated:
        report_lines.append("✅ voice_lines_000.json を更新しました")
        report_lines.append(f"   バックアップ: {VOICE_LINES_PATH.with_suffix('.json.bak')}")
    else:
        report_lines.append("ℹ️ voice_lines_000.json は変更されませんでした")
    
    # サマリー
    text_mismatch_ids = list(mismatches.keys())
    report_lines.append(f"\n📊 サマリー:")
    report_lines.append(f"  - テキスト不一致: {len(mismatches)}件")
    report_lines.append(f"  - 不足音声ファイル: {len(missing_audio)}件")
    report_lines.append(f"  - 孤立音声ファイル: {len(orphan_audio)}件")
    if audio_mismatches is not None:
        report_lines.append(f"  - 音声内容不一致: {len(audio_mismatches)}件")
        if audio_mismatches:
            mismatch_ids = [tid for tid, _, _, _ in audio_mismatches]
            report_lines.append(f"    mismatch_ids: {', '.join(mismatch_ids)}")
    
    if mismatches:
        report_lines.append(f"\n⚠️ 注意: テンプレート {', '.join(sorted(text_mismatch_ids))} のテキストが不一致です")
        report_lines.append("   intent_rules.py が優先されるため、音声ファイルは intent_rules.py の内容で生成してください。")
    
    report_lines.append("")
    report_lines.append("=" * 80)
    
    return "\n".join(report_lines)


def verify_only(template_config: Dict, voice_lines: Dict, audio_files: Set[str], verify_audio: bool = False) -> None:
    """検証のみ実行（更新なし）"""
    print("=" * 80)
    print("クライアント000 音声アセット検証モード")
    print("=" * 80)
    print()
    
    template_ids = set(template_config.keys())
    voice_ids = {k for k in voice_lines.keys() if k != 'voice'}
    
    mismatches = find_mismatches(template_config, voice_lines)
    missing_audio = template_ids - audio_files
    orphan_audio = audio_files - template_ids
    
    total_templates = len(template_ids)
    mismatch_count = len(mismatches)
    missing_count = len(missing_audio)
    orphan_count = len(orphan_audio)
    
    print(f"📊 検証結果:")
    print(f"  - チェック対象テンプレート: {total_templates}件")
    print(f"  - テキスト不一致: {mismatch_count}件")
    print(f"  - 不足音声ファイル: {missing_count}件")
    print(f"  - 孤立音声ファイル: {orphan_count}件")
    print()
    
    if mismatch_count > 0:
        print("⚠️ テキスト不一致:")
        for tid in sorted(mismatches.keys())[:10]:
            old_text, new_text = mismatches[tid]
            print(f"  - {tid}:")
            print(f"    旧: {old_text[:60]}...")
            print(f"    新: {new_text[:60]}...")
        if mismatch_count > 10:
            print(f"  ... 他 {mismatch_count - 10}件")
        print()
    
    if missing_count > 0:
        print(f"⚠️ 不足音声ファイル ({missing_count}件):")
        for tid in sorted(missing_audio)[:10]:
            print(f"  - template_{tid}.wav")
        if missing_count > 10:
            print(f"  ... 他 {missing_count - 10}件")
        print()
    
    if orphan_count > 0:
        print(f"⚠️ 孤立音声ファイル ({orphan_count}件):")
        for tid in sorted(orphan_audio)[:10]:
            print(f"  - template_{tid}.wav")
        if orphan_count > 10:
            print(f"  ... 他 {orphan_count - 10}件")
        print()
    
    # 音声内容検証
    audio_mismatches = None
    if verify_audio:
        audio_mismatches = verify_audio_content(template_config, audio_files)
        if audio_mismatches:
            print(f"\n⚠️ 音声内容不一致 ({len(audio_mismatches)}件):")
            for tid, expected, detected, similarity in audio_mismatches[:10]:
                print(f"  - template_{tid}.wav (一致率: {similarity:.2f})")
                print(f"    期待: {expected[:60]}...")
                print(f"    検出: {detected[:60]}...")
            if len(audio_mismatches) > 10:
                print(f"  ... 他 {len(audio_mismatches) - 10}件")
        else:
            print("\n✅ すべての音声内容が一致しています。")
    
    if mismatch_count == 0 and missing_count == 0 and orphan_count == 0:
        if not verify_audio or (audio_mismatches is not None and len(audio_mismatches) == 0):
            print("\n✅ すべて一致しています。")
    else:
        print("\nℹ️ 修正するには、--verify オプションなしで実行してください。")
    
    print("=" * 80)


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='クライアント000の音声アセット同期スクリプト')
    parser.add_argument('--verify', action='store_true', help='検証のみ実行（更新なし）')
    parser.add_argument('--verify-audio', action='store_true', help='音声内容も検証（Google STT使用）')
    parser.add_argument('--yes', '-y', action='store_true', help='確認なしで実行（孤立音声ファイルの削除も自動実行）')
    parser.add_argument('--similarity-threshold', type=float, default=0.8, help='音声内容一致率の閾値（デフォルト: 0.8）')
    args = parser.parse_args()
    
    print("=" * 80)
    print("クライアント000 音声アセット同期スクリプト")
    print("=" * 80)
    print()
    
    # データ読み込み
    print("📖 データ読み込み中...")
    template_config = TEMPLATE_CONFIG
    voice_lines = load_voice_lines()
    audio_files = get_audio_files()
    
    template_ids = set(template_config.keys())
    voice_ids = {k for k in voice_lines.keys() if k != 'voice'}
    
    # 検証モードの場合は検証のみ実行
    if args.verify:
        verify_only(template_config, voice_lines, audio_files, verify_audio=args.verify_audio)
        return 0
    
    # 不一致検出
    print("🔍 不一致検出中...")
    mismatches = find_mismatches(template_config, voice_lines)
    missing_audio = template_ids - audio_files
    orphan_audio = audio_files - template_ids
    
    # 統計
    total_templates = len(template_ids)
    mismatch_count = len(mismatches)
    missing_count = len(missing_audio)
    orphan_count = len(orphan_audio)
    
    print(f"\n📊 検出結果:")
    print(f"  - チェック対象テンプレート: {total_templates}件")
    print(f"  - テキスト不一致: {mismatch_count}件")
    print(f"  - 不足音声ファイル: {missing_count}件")
    print(f"  - 孤立音声ファイル: {orphan_count}件")
    
    # 更新が必要か確認
    needs_update = bool(mismatches) or bool(voice_ids - template_ids) or bool(template_ids - voice_ids)
    
    if not needs_update and not missing_audio and not orphan_audio:
        print("\n✅ すべて一致しています。更新は不要です。")
        return 0
    
    # バックアップ作成
    if needs_update:
        print("\n💾 バックアップ作成中...")
        backup_voice_lines()
    
    # voice_lines_000.json を更新
    if needs_update:
        print("\n🔄 voice_lines_000.json を更新中...")
        updated_voice_lines = update_voice_lines(template_config, voice_lines)
        save_voice_lines(updated_voice_lines)
        updated = True
    else:
        updated = False
    
    # 孤立音声ファイルの削除確認
    if orphan_audio:
        print(f"\n⚠️ 孤立音声ファイルが {orphan_count}件 見つかりました:")
        for tid in sorted(list(orphan_audio)[:10]):
            print(f"  - template_{tid}.wav")
        if orphan_count > 10:
            print(f"  ... 他 {orphan_count - 10}件")
        
        if args.yes:
            response = 'y'
            print("\n--yes オプションが指定されているため、自動的に削除します。")
        else:
            response = input("\n削除しますか？ (y/n): ").strip().lower()
        
        if response == 'y':
            deleted_count = 0
            for tid in orphan_audio:
                wav_file = AUDIO_DIR / f"template_{tid}.wav"
                if wav_file.exists():
                    wav_file.unlink()
                    deleted_count += 1
            print(f"✅ {deleted_count}件 の音声ファイルを削除しました")
        else:
            print("ℹ️ 削除をスキップしました")
    
    # 音声内容検証
    audio_mismatches = None
    if args.verify_audio:
        audio_mismatches = verify_audio_content(template_config, audio_files, args.similarity_threshold)
        if audio_mismatches:
            print(f"\n⚠️ 音声内容不一致: {len(audio_mismatches)}件")
    
    # レポート生成
    print("\n📝 レポート生成中...")
    report = generate_report(
        template_config,
        voice_lines,
        audio_files,
        mismatches,
        missing_audio,
        orphan_audio,
        updated,
        audio_mismatches
    )
    
    # レポート保存
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"✅ レポート保存: {LOG_FILE}")
    
    # 標準出力にも概要を表示
    print("\n" + "=" * 80)
    print("📋 同期結果サマリー")
    print("=" * 80)
    print(f"[SYNC_REPORT] Checked {total_templates} templates")
    if missing_audio:
        missing_list = ", ".join([f"template_{tid}.wav" for tid in sorted(list(missing_audio)[:5])])
        if missing_count > 5:
            missing_list += f", ... (他 {missing_count - 5}件)"
        print(f"- Missing audio files: {missing_count} ({missing_list})")
    if mismatch_count > 0:
        print(f"- Mismatched text entries: {mismatch_count}")
    if audio_mismatches:
        audio_list = ", ".join([f"template_{tid}.wav" for tid, _, _, _ in audio_mismatches[:5]])
        if len(audio_mismatches) > 5:
            audio_list += f", ... (他 {len(audio_mismatches) - 5}件)"
        print(f"- Mismatched audio content: {len(audio_mismatches)} ({audio_list})")
    if updated:
        print(f"- Updated: voice_lines_000.json")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ 処理が中断されました")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
