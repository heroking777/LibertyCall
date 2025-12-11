#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASR評価スクリプト（WER: Word Error Rate）

Whisper認識結果の品質を定量的に把握し、
音声テストの「ASR品質チェック」を自動化します。

使い方:
    python3 scripts/asr_eval.py
    python3 scripts/asr_eval.py --threshold 0.10
"""

import sys
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple

# プロジェクトルートを取得
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TTS_TEST_DIR = PROJECT_ROOT / "tts_test"
EVAL_DIR = TTS_TEST_DIR / "results"
REFERENCE_FILE = TTS_TEST_DIR / "reference_texts.json"
OUTPUT_JSON = PROJECT_ROOT / "logs" / "asr_eval_results.json"

# WER計算用ライブラリ
try:
    from jiwer import wer, cer  # Word Error Rate, Character Error Rate
    JIWER_AVAILABLE = True
except ImportError:
    JIWER_AVAILABLE = False
    # 簡易版WER計算（Levenshtein距離ベース）
    try:
        from Levenshtein import distance as levenshtein_distance
        LEVENSHTEIN_AVAILABLE = True
    except ImportError:
        LEVENSHTEIN_AVAILABLE = False

def simple_wer(reference: str, hypothesis: str) -> float:
    """
    簡易版WER計算（Levenshtein距離ベース）
    jiwerが使えない場合のフォールバック
    """
    if not LEVENSHTEIN_AVAILABLE:
        # 最も簡易な方法：文字列一致率
        if not reference:
            return 1.0 if hypothesis else 0.0
        if not hypothesis:
            return 1.0
        
        ref_words = reference.split()
        hyp_words = hypothesis.split()
        
        if not ref_words:
            return 1.0 if hyp_words else 0.0
        if not hyp_words:
            return 1.0
        
        # 単語レベルでの編集距離を近似
        max_len = max(len(ref_words), len(hyp_words))
        if max_len == 0:
            return 0.0
        
        # 簡易版：一致する単語数をカウント
        ref_set = set(ref_words)
        hyp_set = set(hyp_words)
        common = len(ref_set & hyp_set)
        total = len(ref_set | hyp_set)
        
        return 1.0 - (common / total) if total > 0 else 0.0
    
    # Levenshtein距離を使用
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    
    if not ref_words:
        return 1.0 if hyp_words else 0.0
    if not hyp_words:
        return 1.0
    
    # 単語列の編集距離を計算
    ref_str = " ".join(ref_words)
    hyp_str = " ".join(hyp_words)
    
    max_len = max(len(ref_str), len(hyp_str))
    if max_len == 0:
        return 0.0
    
    distance = levenshtein_distance(ref_str, hyp_str)
    return distance / max_len

def calculate_wer(reference: str, hypothesis: str) -> float:
    """
    WER（Word Error Rate）を計算
    
    :param reference: 期待テキスト
    :param hypothesis: 認識結果
    :return: WER値（0.0～1.0、小さいほど良い）
    """
    if not reference and not hypothesis:
        return 0.0
    
    if JIWER_AVAILABLE:
        try:
            return wer(reference, hypothesis)
        except Exception as e:
            print(f"⚠️  jiwer計算エラー: {e}", file=sys.stderr)
            return simple_wer(reference, hypothesis)
    else:
        return simple_wer(reference, hypothesis)

def load_reference_texts() -> Dict[str, str]:
    """
    期待テキストを読み込む
    
    :return: {ファイル名: 期待テキスト} の辞書
    """
    if not REFERENCE_FILE.exists():
        print(f"⚠️  警告: 期待テキストファイルが見つかりません: {REFERENCE_FILE}")
        print("   空の辞書を返します。")
        return {}
    
    try:
        with open(REFERENCE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ エラー: 期待テキストファイルの読み込みに失敗しました: {e}", file=sys.stderr)
        return {}

def load_recognized_texts() -> Dict[str, str]:
    """
    認識結果を読み込む
    
    :return: {ファイル名: 認識テキスト} の辞書
    """
    recognized = {}
    
    if not EVAL_DIR.exists():
        print(f"⚠️  警告: 評価結果ディレクトリが見つかりません: {EVAL_DIR}")
        return recognized
    
    # results/*.txt を読み込む
    for txt_file in EVAL_DIR.glob("*.txt"):
        fname = txt_file.stem  # 拡張子を除いたファイル名
        try:
            with open(txt_file, "r", encoding="utf-8") as f:
                recognized[fname] = f.read().strip()
        except Exception as e:
            print(f"⚠️  警告: {txt_file} の読み込みに失敗しました: {e}", file=sys.stderr)
    
    return recognized

def evaluate_asr(threshold: float = 0.10) -> Tuple[List[Dict], float, int]:
    """
    ASR評価を実行
    
    :param threshold: 合格ライン（平均WER）
    :return: (評価結果リスト, 平均WER, サンプル数)
    """
    reference_texts = load_reference_texts()
    recognized_texts = load_recognized_texts()
    
    if not reference_texts:
        print("❌ エラー: 期待テキストが定義されていません。")
        print(f"   {REFERENCE_FILE} を作成してください。")
        return [], 0.0, 0
    
    if not recognized_texts:
        print("❌ エラー: 認識結果が見つかりません。")
        print(f"   {EVAL_DIR} に認識結果ファイル（*.txt）を配置してください。")
        return [], 0.0, 0
    
    results = []
    total_wer = 0.0
    count = 0
    
    # 各ファイルを評価
    for fname, expected_text in reference_texts.items():
        if fname not in recognized_texts:
            print(f"⚠️  {fname}: 認識結果が見つかりません（スキップ）")
            continue
        
        recognized = recognized_texts[fname]
        
        # 認識結果からファイル名の数字プレフィックスを除去（例: "004もしもし" → "もしもし"）
        # ファイル名が数字で始まる場合、認識結果の先頭に数字が含まれる可能性がある
        import re
        # 先頭の数字を除去
        recognized_cleaned = re.sub(r'^\d+', '', recognized).strip()
        if not recognized_cleaned:
            recognized_cleaned = recognized
        
        wer_score = calculate_wer(expected_text, recognized_cleaned)
        
        results.append({
            "file": fname,
            "expected": expected_text,
            "recognized": recognized_cleaned,
            "wer": wer_score,
            "status": "PASS" if wer_score < threshold else "FAIL"
        })
        
        print(f"{fname}: {wer_score:.3f}")
        total_wer += wer_score
        count += 1
    
    avg_wer = total_wer / max(count, 1)
    
    return results, avg_wer, count

def save_results_json(results: List[Dict], avg_wer: float, count: int, threshold: float):
    """
    評価結果をJSON形式で保存（Webダッシュボード用）
    
    :param results: 評価結果リスト
    :param avg_wer: 平均WER
    :param count: サンプル数
    :param threshold: 合格ライン
    """
    output_data = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "summary": {
            "total_samples": count,
            "avg_wer": avg_wer,
            "threshold": threshold,
            "status": "PASS" if avg_wer < threshold else "FAIL"
        },
        "results": results
    }
    
    # ログディレクトリを作成
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"\n💾 評価結果を保存しました: {OUTPUT_JSON}")
    except Exception as e:
        print(f"⚠️  警告: 評価結果の保存に失敗しました: {e}", file=sys.stderr)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="ASR評価スクリプト（WER計算）")
    parser.add_argument("--threshold", type=float, default=0.10, help="合格ライン（平均WER、デフォルト: 0.10）")
    parser.add_argument("--no-json", action="store_true", help="JSON出力をスキップ")
    args = parser.parse_args()
    
    # ライブラリの確認
    if not JIWER_AVAILABLE and not LEVENSHTEIN_AVAILABLE:
        print("⚠️  警告: jiwer または python-Levenshtein がインストールされていません。")
        print("   簡易版WER計算を使用します（精度が低下する可能性があります）。")
        print("   推奨: pip install jiwer")
        print("")
    
    # 評価実行
    results, avg_wer, count = evaluate_asr(threshold=args.threshold)
    
    if count == 0:
        sys.exit(1)
    
    # サマリー表示
    print("")
    print("=" * 60)
    print("📊 ASR Evaluation Summary")
    print("=" * 60)
    print(f"Total Samples: {count}")
    print(f"Avg WER: {avg_wer:.3f}")
    print(f"Threshold: {args.threshold:.3f}")
    
    if avg_wer < args.threshold:
        print("✅ Whisper accuracy within expected range.")
        status_code = 0
    else:
        print("⚠️  Accuracy degradation detected.")
        status_code = 1
    
    print("=" * 60)
    
    # JSON出力
    if not args.no_json:
        save_results_json(results, avg_wer, count, args.threshold)
    
    sys.exit(status_code)

if __name__ == "__main__":
    main()

