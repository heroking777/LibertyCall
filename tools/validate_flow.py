#!/usr/bin/env python3
"""
会話フロー検証ツール

flow.json の構文・参照チェックを自動で行う
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Set


def load_json_file(path: str) -> dict:
    """JSONファイルを読み込む"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_flow(flow_path: str) -> tuple[bool, List[str]]:
    """
    会話フローを検証する
    
    :param flow_path: flow.json のパス
    :return: (is_valid, errors)
    """
    errors: List[str] = []
    
    try:
        flow = load_json_file(flow_path)
    except json.JSONDecodeError as e:
        return False, [f"JSON構文エラー: {e}"]
    except FileNotFoundError:
        return False, [f"ファイルが見つかりません: {flow_path}"]
    
    # version チェック
    if "version" not in flow:
        errors.append("❌ 'version' フィールドがありません")
    
    # phases チェック
    if "phases" not in flow:
        errors.append("❌ 'phases' フィールドがありません")
        return False, errors
    
    phases = flow["phases"]
    
    # テンプレートとキーワードを読み込む
    flow_dir = Path(flow_path).parent
    templates_path = flow_dir / "templates.json"
    keywords_path = flow_dir / "keywords.json"
    
    templates: Dict[str, dict] = {}
    if templates_path.exists():
        templates = load_json_file(str(templates_path))
    
    keywords: Dict[str, List[str]] = {}
    if keywords_path.exists():
        keywords = load_json_file(str(keywords_path))
    
    # フェーズごとに検証
    referenced_templates: Set[str] = set()
    referenced_keywords: Set[str] = set()
    
    for phase_name, phase_config in phases.items():
        # transitions チェック
        if "transitions" not in phase_config:
            errors.append(f"❌ phase '{phase_name}': 'transitions' フィールドがありません")
            continue
        
        # templates チェック
        if "templates" in phase_config:
            phase_templates = phase_config["templates"]
            if isinstance(phase_templates, list):
                for template_id in phase_templates:
                    referenced_templates.add(template_id)
                    if templates and template_id not in templates:
                        errors.append(f"⚠️  phase '{phase_name}': テンプレート '{template_id}' が templates.json に存在しません")
        
        # transitions 内のキーワード参照をチェック
        for transition in phase_config.get("transitions", []):
            condition = transition.get("condition", "")
            # キーワード参照を抽出（簡易版）
            if "ENTRY_TRIGGER_KEYWORDS" in condition:
                referenced_keywords.add("ENTRY_TRIGGER_KEYWORDS")
            if "CLOSING_YES_KEYWORDS" in condition:
                referenced_keywords.add("CLOSING_YES_KEYWORDS")
            if "CLOSING_NO_KEYWORDS" in condition:
                referenced_keywords.add("CLOSING_NO_KEYWORDS")
            if "AFTER_085_NEGATIVE_KEYWORDS" in condition:
                referenced_keywords.add("AFTER_085_NEGATIVE_KEYWORDS")
    
    # キーワード参照チェック
    for keyword_name in referenced_keywords:
        if keywords and keyword_name not in keywords:
            errors.append(f"⚠️  キーワード '{keyword_name}' が keywords.json に存在しません")
    
    # handoff_flow チェック
    if "handoff_flow" in flow:
        handoff_flow = flow["handoff_flow"]
        if "confirmation_flow" in handoff_flow:
            confirmation_flow = handoff_flow["confirmation_flow"]
            for flow_type, flow_config in confirmation_flow.items():
                if "templates" in flow_config:
                    for template_id in flow_config["templates"]:
                        referenced_templates.add(template_id)
                        if templates and template_id not in templates:
                            errors.append(f"⚠️  handoff_flow.confirmation_flow.{flow_type}: テンプレート '{template_id}' が templates.json に存在しません")
    
    is_valid = len(errors) == 0
    return is_valid, errors


def main():
    """メイン関数"""
    if len(sys.argv) < 2:
        print("使用方法: python3 validate_flow.py <flow.jsonのパス>")
        print("例: python3 validate_flow.py /opt/libertycall/config/clients/000/flow.json")
        sys.exit(1)
    
    flow_path = sys.argv[1]
    
    print(f"🔍 会話フローを検証中: {flow_path}")
    print("=" * 60)
    
    is_valid, errors = validate_flow(flow_path)
    
    if is_valid:
        print("✅ 検証成功: エラーは見つかりませんでした")
        sys.exit(0)
    else:
        print("❌ 検証失敗: 以下のエラーが見つかりました:")
        print()
        for error in errors:
            print(f"  {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()

