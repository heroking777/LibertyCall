#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音声再生管理

クライアント別の着信音声シーケンスを管理し、音声ファイルを読み込んで再生する
"""

print("DEBUG: LOADING AUDIO MANAGER FROM /opt/libertycall_fixed/gateway/audio_manager.py")

import glob
import logging
from pathlib import Path
from typing import List, Optional

try:
    from .utils.client_config_loader import ClientConfigLoader
except ImportError:  # スクリプト直接実行時の互換性確保
    from utils.client_config_loader import ClientConfigLoader  # type: ignore


logger = logging.getLogger(__name__)


class AudioManager:
    """音声再生を管理するクラス"""
    
    def __init__(self, project_root: Optional[Path] = None):
        """
        初期化
        
        Args:
            project_root: プロジェクトルートのパス
        """
        self.config_loader = ClientConfigLoader(project_root)
        self.project_root = self.config_loader.project_root
        self._client_cache = {}  # クライアントごとの設定キャッシュ
        self.logger = logging.getLogger(__name__)
        self.logger.error("!!! AUDIO_MANAGER_INITIALIZED_AT_PATH: {} !!!".format(__file__))
        self.logger.error("!!! AUDIO_MANAGER_INITIALIZED_AT_PATH: {} !!!".format(__file__))
    
    def get_incoming_sequence(self, client_id: str) -> List[str]:
        """
        クライアントの着信音声シーケンスを取得
        
        Args:
            client_id: クライアントID（例: "000"）
        
        Returns:
            音声IDのリスト（例: ["000", "001", "002"]）
        """
        # キャッシュがあれば使用
        if client_id in self._client_cache:
            return self._client_cache[client_id]
        
        try:
            sequence = self.config_loader.load_incoming_sequence(client_id)
            self._client_cache[client_id] = sequence
            return sequence
        except Exception as e:
            logger.error(f"Failed to load incoming sequence for client {client_id}: {e}")
            # フォールバック: 空のリストを返す
            return []
    
    def get_audio_file_paths(self, client_id: str, audio_ids: List[str]) -> List[Path]:
        """
        音声ファイルのパスリストを取得
        
        Args:
            client_id: クライアントID
            audio_ids: 音声IDのリスト
        
        Returns:
            音声ファイルのパスリスト
        """
        paths = []
        for audio_id in audio_ids:
            path = self.config_loader.get_audio_file_path(client_id, audio_id)
            paths.append(path)
        return paths

    def get_audio_files_for_client(self, client_id: str) -> List[Path]:
        """
        指定されたクライアントの音声ファイル一覧を取得

        Args:
            client_id: クライアントID

        Returns:
            音声ファイルのPathリスト
        """
        audio_dir = Path(self.project_root or "/opt/libertycall") / "clients" / client_id / "audio"
        audio_files = [Path(p) for p in glob.glob(f"{audio_dir}/*.wav")]
        audio_files.sort()
        logger.info(f"[AUDIO_LOADER] Found {len(audio_files)} audio files in {audio_dir}")
        return audio_files

    def play_incoming_sequence(self, client_id: str) -> List[Path]:
        """
        着信時の音声シーケンスを取得（再生用）
        
        Args:
            client_id: クライアントID
        
        Returns:
            音声ファイルのパスリスト
        """
        logger.warning(f"[PLAY_SEQ_START] play_incoming_sequence called for client_id={client_id}")
        # 利用可能なクライアント情報を取得（config_loader経由）
        try:
            available_clients = self.config_loader.list_clients()
            logger.warning(f"[PLAY_SEQ_CLIENTS] Available clients: {available_clients}")
        except Exception as e:
            logger.warning(f"[PLAY_SEQ_CLIENTS] Failed to list clients: {e}")
        
        sequence = self.get_incoming_sequence(client_id)
        
        # ログ出力（ユーザー要求の形式に合わせる）
        logger.info(f"[client={client_id}] incoming call audio sequence: {sequence}")
        logger.warning(f"[PLAY_SEQ_CLIENT_DATA] sequence={sequence}")
        
        # 音声ファイルのパスを取得
        audio_paths = self.get_audio_file_paths(client_id, sequence)
        if not audio_paths:
            self.logger.warning(f"[PLAY_SEQ_FALLBACK] No configured audio paths for client={client_id}, falling back to directory scan")
            audio_paths = self.get_audio_files_for_client(client_id)
        logger.warning(f"[PLAY_SEQ_AUDIO_PATHS] audio_paths={[str(p) for p in audio_paths]} (count={len(audio_paths) if audio_paths else 0})")
        
        # ファイルの存在確認
        missing_files = [p for p in audio_paths if not p.exists()]
        if missing_files:
            logger.warning(
                f"[client={client_id}] Missing audio files: "
                f"{[str(p) for p in missing_files]}"
            )
        
        file_info = []
        for p in audio_paths:
            size = None
            if p.exists():
                try:
                    size = p.stat().st_size
                except OSError:
                    size = None
            try:
                rel = str(p.relative_to(self.project_root))
            except ValueError:
                rel = str(p)
            file_info.append({"path": rel, "size": size})
        logger.info(f"[client={client_id}] incoming audio files={file_info}")
        
        return audio_paths

