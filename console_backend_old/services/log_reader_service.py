"""ログファイル読み取りサービス."""

import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict


class LogReaderService:
    """ログファイル読み取りサービス."""
    
    # ログ行の正規表現パターン
    # 例: [2025-12-05 13:11:24] [-] USER  いや、あのシステムについて聞きたいんですよ。
    # 例: [2025-12-05 13:11:24] [-] AI (tpl=010) どのような点が気になっておりますでしょうか？
    LOG_PATTERN = re.compile(
        r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[([^\]]+)\] (\w+)(?:\s+\(tpl=(\d+)\))?\s*(.+)$'
    )
    
    def __init__(self, logs_base_dir: Path):
        """
        初期化.
        
        Args:
            logs_base_dir: ログファイルのベースディレクトリ（例: /opt/libertycall/logs/calls）
        """
        self.logs_base_dir = Path(logs_base_dir)
    
    def parse_log_line(self, line: str) -> Optional[Dict[str, Any]]:
        """
        ログ行をパース.
        
        Args:
            line: ログ行文字列
            
        Returns:
            パース結果（timestamp, caller_number, role, template_id, text）またはNone
        """
        line = line.strip()
        if not line:
            return None
        
        match = self.LOG_PATTERN.match(line)
        if not match:
            return None
        
        timestamp_str, caller_number, role, template_id, text = match.groups()
        
        # timestampをパース
        try:
            # ログファイルの時刻はJSTなので、UTC に変換
            JST = timezone(timedelta(hours=9))
            jst_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
            timestamp = jst_time.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            return None
        
        # caller_numberが "-" の場合は None
        caller_number = caller_number if caller_number != "-" else None
        
        # roleを大文字に統一
        role = role.upper()
        
        # USER/AI以外の行（SYSTEM等）はスキップ
        if role not in ("USER", "AI"):
            return None
        
        # template_idを数値のみ抽出（既に正規表現で抽出済み）
        template_id = template_id if template_id else None
        
        # textの前後の余計な半角スペースだけを削除（全角スペースや本文は保持）
        # ただし、行末の改行文字は既にstrip()で削除済み
        text = text.strip()  # 前後の半角スペース・タブ・改行を削除
        
        return {
            "timestamp": timestamp,
            "caller_number": caller_number,
            "role": role,
            "template_id": template_id,
            "text": text,
        }
    
    def read_call_log(self, client_id: str, call_id: str) -> Dict[str, Any]:
        """
        1通話のログを読み取り.
        
        Args:
            client_id: クライアントID
            call_id: 通話ID（ファイル名から拡張子を除いたもの）
            
        Returns:
            通話情報とログエントリの辞書（call_id, client_id, caller_number, started_at, logs）
        """
        # ファイルパスを構築
        log_file = self.logs_base_dir / client_id / f"{call_id}.log"
        
        if not log_file.exists():
            return {
                "call_id": call_id,
                "client_id": client_id,
                "caller_number": None,
                "started_at": None,
                "logs": []
            }
        
        logs = []
        caller_number = None
        started_at = None
        
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    parsed = self.parse_log_line(line)
                    if parsed:
                        # 最初のログのタイムスタンプを開始時刻として記録
                        if started_at is None:
                            started_at = parsed["timestamp"]
                        
                        # 最初のUSERログからcaller_numberを取得
                        if caller_number is None and parsed["role"] == "USER" and parsed["caller_number"]:
                            caller_number = parsed["caller_number"]
                        
                        logs.append(parsed)
            
            # タイムスタンプでソート（昇順）
            # ファイル内の出現順を維持（timestampのみでソート、同一時刻は元の順序を保持）
            # sorted は安定ソートなので同一キーの場合は元の順序が維持される
            logs.sort(key=lambda x: x["timestamp"])
        except Exception as e:
            # エラーログを出力（実際の実装ではloggerを使用）
            print(f"Error reading log file {log_file}: {e}")
            return {
                "call_id": call_id,
                "client_id": client_id,
                "caller_number": None,
                "started_at": None,
                "logs": []
            }
        
        return {
            "call_id": call_id,
            "client_id": client_id,
            "caller_number": caller_number,
            "started_at": started_at,
            "logs": logs
        }
    
    def list_calls_for_date(
        self, client_id: str, date: datetime
    ) -> List[Dict[str, Any]]:
        """
        指定日の通話一覧を取得.
        
        Args:
            client_id: クライアントID
            date: 日付
            
        Returns:
            通話一覧（call_id, started_at, caller_number, summary）
        """
        client_dir = self.logs_base_dir / client_id
        
        if not client_dir.exists():
            return []
        
        # 指定日のログファイルを検索
        date_str = date.strftime("%Y-%m-%d")
        calls = []
        
        # ログファイルを走査
        for log_file in client_dir.glob("*.log"):
            # TEMP_CALL.log の場合は call_id を "TEMP_CALL" として扱う
            if log_file.name == "TEMP_CALL.log":
                call_id = "TEMP_CALL"
            else:
                call_id = log_file.stem  # 拡張子を除いたファイル名
            
            # ログを読み取り
            call_data = self.read_call_log(client_id, call_id)
            logs = call_data["logs"]
            if not logs:
                continue
            
            # 指定日のログが含まれているか確認
            date_logs = [log for log in logs if log["timestamp"].strftime("%Y-%m-%d") == date_str]
            if not date_logs:
                continue
            
            # 指定日の最初のログのタイムスタンプを開始時間とする
            started_at = date_logs[0]["timestamp"]
            
            # caller_numberと要約を取得
            caller_number = call_data["caller_number"]
            summary = self._extract_summary(logs)
            
            calls.append({
                "call_id": call_id,
                "started_at": started_at,
                "caller_number": caller_number,
                "summary": summary or "",
            })
        
        # 開始時間でソート（新しい順）
        calls.sort(key=lambda x: x["started_at"], reverse=True)
        
        return calls
    
    def list_all_client_ids(self) -> List[str]:
        """
        すべてのクライアントIDを取得.
        
        Returns:
            クライアントIDのリスト
        """
        if not self.logs_base_dir.exists():
            return []
        
        client_ids = []
        for item in self.logs_base_dir.iterdir():
            if item.is_dir():
                client_ids.append(item.name)
        
        return sorted(client_ids)
    
    def _extract_summary(self, log_entries: List[Dict[str, Any]]) -> str:
        """
        通話ログの概要を作成する.
        
        - 最初の USER 発話を使用
        - handoff の場合は専用の短い summary
        - テキストは最大 40〜50 文字
        
        Args:
            log_entries: ログエントリのリスト
            
        Returns:
            要約文字列
        """
        for entry in log_entries:
            if entry["role"] == "USER":
                text = entry["text"].strip()
                
                if not text:
                    continue
                
                # handoff系キーワードで要約を置き換え
                if "担当者" in text or "転送" in text or "つなぎ" in text or "つないで" in text:
                    return "担当者希望"
                if "折返" in text or "折り返" in text or "折り返し" in text:
                    return "折返し希望"
                
                # 予約・営業関連キーワード
                if "予約" in text or "営業" in text:
                    if "確認" in text:
                        return "予約内容の確認"
                    return "予約・営業関連"
                
                # 50文字でトリム
                return text[:50] + ("..." if len(text) > 50 else "")
        
        # USER行が無い場合
        return "内容なし"

