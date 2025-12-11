#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
クライアント設定ローダー

クライアントごとの設定ファイル（incoming_sequence.json等）を読み込む
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional


class ClientConfigLoader:
    """クライアント設定を読み込むクラス"""
    
    def __init__(self, project_root: Optional[Path] = None):
        """
        初期化
        
        Args:
            project_root: プロジェクトルートのパス（Noneの場合は自動検出）
        """
        if project_root is None:
            # このファイルからプロジェクトルートを推定
            # gateway/utils/client_config_loader.py -> /opt/libertycall
            self.project_root = Path(__file__).parent.parent.parent
        else:
            self.project_root = Path(project_root)
        
        self.clients_dir = self.project_root / "clients"
    
    def get_client_id_from_did(self, did: str) -> str:
        """
        DID（電話番号）からクライアントIDを取得
        
        現在は固定で"000"を返す（将来拡張可能）
        
        Args:
            did: 電話番号（例: "05058304073"）
        
        Returns:
            クライアントID（例: "000"）
        """
        # TODO: DIDとクライアントIDのマッピングを実装
        # 現時点では固定で"000"を返す
        return "000"
    
    def load_incoming_sequence(self, client_id: str) -> List[str]:
        """
        クライアントの着信音声シーケンスを読み込む
        
        Args:
            client_id: クライアントID（例: "000"）
        
        Returns:
            音声IDのリスト（例: ["000", "001", "002"]）
        
        Raises:
            FileNotFoundError: 設定ファイルが見つからない場合
            json.JSONDecodeError: JSONの解析に失敗した場合
        """
        config_file = self.clients_dir / client_id / "config" / "incoming_sequence.json"
        
        if not config_file.exists():
            raise FileNotFoundError(
                f"Client config not found: {config_file}"
            )
        
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        sequence = config.get("incoming_sequence", [])
        if not isinstance(sequence, list):
            raise ValueError(
                f"Invalid incoming_sequence format in {config_file}: "
                f"expected list, got {type(sequence)}"
            )
        
        return sequence
    
    def get_audio_file_path(self, client_id: str, audio_id: str) -> Path:
        """
        音声ファイルのパスを取得
        
        Args:
            client_id: クライアントID（例: "000"）
            audio_id: 音声ID（例: "000"）
        
        Returns:
            音声ファイルのパス
        """
        audio_file = self.clients_dir / client_id / "audio" / f"{audio_id}.wav"
        return audio_file
    
    def validate_audio_files(self, client_id: str, audio_ids: List[str]) -> bool:
        """
        音声ファイルの存在を確認
        
        Args:
            client_id: クライアントID
            audio_ids: 音声IDのリスト
        
        Returns:
            すべてのファイルが存在する場合True
        """
        for audio_id in audio_ids:
            audio_path = self.get_audio_file_path(client_id, audio_id)
            if not audio_path.exists():
                return False
        return True











