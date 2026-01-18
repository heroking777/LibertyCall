"""本番環境でのパフォーマンステスト."""

import os
import pytest
import time
from datetime import datetime, UTC
from concurrent.futures import ThreadPoolExecutor, as_completed

from console_backend.service_client import start_call, append_call_log, complete_call
from console_backend.database import SessionLocal, Base, engine
from console_backend.models import Call, CallLog


class TestProductionPerformance:
    """本番環境でのパフォーマンステスト."""

    CALLS_PER_SECOND_MIN = float(os.getenv("PERF_CALLS_PER_SECOND_MIN", "3"))
    LOGS_PER_SECOND_MIN = float(os.getenv("PERF_LOGS_PER_SECOND_MIN", "50"))

    @classmethod
    def setup_class(cls) -> None:
        Base.metadata.create_all(bind=engine)

    def setup_method(self) -> None:
        self._cleanup_perf_data()

    def teardown_method(self) -> None:
        self._cleanup_perf_data()

    @staticmethod
    def _cleanup_perf_data() -> None:
        with SessionLocal() as db:
            db.query(CallLog).filter(CallLog.call_id.like("perf-%")).delete()
            db.query(Call).filter(Call.call_id.like("perf-%")).delete()
            db.commit()
    
    def test_concurrent_calls(self):
        """並行通話のパフォーマンステスト."""
        num_calls = 50
        num_logs_per_call = 10
        
        def create_call_with_logs(call_id: int):
            """通話とログを作成."""
            call_id_str = f"perf-test-{call_id}"
            client_id = f"client-{call_id % 10}"
            
            start_time = time.time()
            
            # 通話開始
            start_call(call_id_str, client_id, state="init")
            
            # ログを追加
            for i in range(num_logs_per_call):
                append_call_log(
                    call_id_str,
                    role="user" if i % 2 == 0 else "ai",
                    text=f"メッセージ {i}",
                    state="greeting" if i < 3 else "conversation"
                )
            
            # 通話完了
            complete_call(call_id_str, ended_at=datetime.now(UTC))
            
            elapsed = time.time() - start_time
            return call_id_str, elapsed
        
        # 並行実行
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_call_with_logs, i) for i in range(num_calls)]
            results = [future.result() for future in as_completed(futures)]
        
        total_time = time.time() - start_time
        
        # 結果の確認
        with SessionLocal() as db:
            created_calls = db.query(Call).filter(Call.call_id.like("perf-test-%")).count()
            created_logs = db.query(CallLog).filter(CallLog.call_id.like("perf-test-%")).count()
        
        # パフォーマンス指標
        avg_time_per_call = sum(r[1] for r in results) / len(results)
        calls_per_second = num_calls / total_time
        
        print(f"\n=== パフォーマンステスト結果 ===")
        print(f"通話数: {num_calls}")
        print(f"通話あたりのログ数: {num_logs_per_call}")
        print(f"総実行時間: {total_time:.2f}秒")
        print(f"通話あたりの平均時間: {avg_time_per_call:.3f}秒")
        print(f"スループット: {calls_per_second:.2f} 通話/秒")
        print(f"作成された通話: {created_calls}")
        print(f"作成されたログ: {created_logs}")
        
        # アサーション
        assert created_calls == num_calls, f"期待される通話数: {num_calls}, 実際: {created_calls}"
        assert created_logs == num_calls * num_logs_per_call, \
            f"期待されるログ数: {num_calls * num_logs_per_call}, 実際: {created_logs}"
        
        # パフォーマンス要件（例: 1秒あたり10通話以上）
        assert (
            calls_per_second >= self.CALLS_PER_SECOND_MIN
        ), f"スループットが低すぎます: {calls_per_second:.2f} 通話/秒"
        
        # クリーンアップ
        with SessionLocal() as db:
            db.query(CallLog).filter(CallLog.call_id.like("perf-test-%")).delete()
            db.query(Call).filter(Call.call_id.like("perf-test-%")).delete()
            db.commit()
    
    def test_bulk_log_insertion(self):
        """大量ログの挿入パフォーマンステスト."""
        call_id = "perf-bulk-logs"
        client_id = "bulk-client"
        num_logs = 1000
        
        # 通話開始
        start_call(call_id, client_id, state="init")
        
        start_time = time.time()
        
        # 大量のログを追加
        for i in range(num_logs):
            append_call_log(
                call_id,
                role="user" if i % 2 == 0 else "ai",
                text=f"バルクログメッセージ {i}",
                state="conversation"
            )
        
        elapsed = time.time() - start_time
        
        # 確認
        with SessionLocal() as db:
            logs_count = db.query(CallLog).filter(CallLog.call_id == call_id).count()
        
        logs_per_second = num_logs / elapsed
        
        print(f"\n=== バルクログ挿入テスト結果 ===")
        print(f"ログ数: {num_logs}")
        print(f"実行時間: {elapsed:.2f}秒")
        print(f"スループット: {logs_per_second:.2f} ログ/秒")
        print(f"実際のログ数: {logs_count}")
        
        assert logs_count == num_logs, f"期待されるログ数: {num_logs}, 実際: {logs_count}"
        assert (
            logs_per_second >= self.LOGS_PER_SECOND_MIN
        ), f"スループットが低すぎます: {logs_per_second:.2f} ログ/秒"
        
        # クリーンアップ
        with SessionLocal() as db:
            db.query(CallLog).filter(CallLog.call_id == call_id).delete()
            db.query(Call).filter(Call.call_id == call_id).delete()
            db.commit()
    
    def test_query_performance(self):
        """クエリのパフォーマンステスト."""
        # テストデータを作成
        num_calls = 100
        for i in range(num_calls):
            call_id = f"query-test-{i}"
            start_call(call_id, f"client-{i % 10}", state="init")
            for j in range(5):
                append_call_log(
                    call_id,
                    role="user" if j % 2 == 0 else "ai",
                    text=f"メッセージ {j}",
                    state="conversation"
                )
        
        # クエリパフォーマンステスト
        with SessionLocal() as db:
            # 1. 全通話取得
            start_time = time.time()
            calls = db.query(Call).filter(Call.call_id.like("query-test-%")).all()
            query1_time = time.time() - start_time
            
            # 2. クライアント別取得
            start_time = time.time()
            client_calls = db.query(Call).filter(Call.client_id == "client-0").all()
            query2_time = time.time() - start_time
            
            # 3. ログ取得（JOIN）
            start_time = time.time()
            calls_with_logs = db.query(Call).filter(Call.call_id.like("query-test-%")).all()
            for call in calls_with_logs:
                logs = db.query(CallLog).filter(CallLog.call_id == call.call_id).all()
            query3_time = time.time() - start_time
        
        print(f"\n=== クエリパフォーマンステスト結果 ===")
        print(f"全通話取得 ({len(calls)}件): {query1_time*1000:.2f}ms")
        print(f"クライアント別取得 ({len(client_calls)}件): {query2_time*1000:.2f}ms")
        print(f"ログ取得 (JOIN): {query3_time*1000:.2f}ms")
        
        # パフォーマンス要件
        assert query1_time < 1.0, f"全通話取得が遅すぎます: {query1_time:.2f}秒"
        assert query2_time < 0.5, f"クライアント別取得が遅すぎます: {query2_time:.2f}秒"
        
        # クリーンアップ
        with SessionLocal() as db:
            db.query(CallLog).filter(CallLog.call_id.like("query-test-%")).delete()
            db.query(Call).filter(Call.call_id.like("query-test-%")).delete()
            db.commit()

