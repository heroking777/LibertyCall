"""
クライアントIDマッピング機能

発信者番号・着信番号・SIPヘッダなどから client_id を自動判定する
"""
import json
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# マッピング設定のキャッシュ
_mapping_cache: Optional[dict] = None
_mapping_cache_path: Optional[str] = None


def load_client_mapping() -> dict:
    """
    クライアントマッピング設定を読み込む
    
    :return: マッピング設定（dict）
    """
    global _mapping_cache, _mapping_cache_path
    
    mapping_path = "/opt/libertycall/config/client_mapping.json"
    
    # キャッシュが有効な場合は再利用
    if _mapping_cache is not None and _mapping_cache_path == mapping_path:
        if os.path.exists(mapping_path):
            # ファイルの更新時刻をチェック
            current_mtime = os.path.getmtime(mapping_path)
            cached_mtime = _mapping_cache.get("_mtime", 0)
            if current_mtime <= cached_mtime:
                return _mapping_cache
    
    # ファイルを読み込む
    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping = json.load(f)
            mapping["_mtime"] = os.path.getmtime(mapping_path)
            _mapping_cache = mapping
            _mapping_cache_path = mapping_path
            logger.debug(f"[CLIENT_MAPPER] Loaded mapping from {mapping_path}")
            return mapping
    else:
        # デフォルト設定
        default_mapping = {
            "mappings": {
                "by_caller_number": {},
                "by_destination_number": {},
                "by_sip_header": {}
            },
            "default_client_id": "000"
        }
        _mapping_cache = default_mapping
        _mapping_cache_path = mapping_path
        logger.warning(f"[CLIENT_MAPPER] Mapping file not found, using default: {mapping_path}")
        return default_mapping


def get_client_id_from_caller_number(caller_number: Optional[str]) -> Optional[str]:
    """
    発信者番号から client_id を取得
    
    :param caller_number: 発信者番号（例: "08012345678"）
    :return: client_id または None
    """
    if not caller_number:
        return None
    
    mapping = load_client_mapping()
    caller_mappings = mapping.get("mappings", {}).get("by_caller_number", {})
    
    # プレフィックスマッチング
    for prefix, client_id in caller_mappings.items():
        if caller_number.startswith(prefix):
            logger.debug(f"[CLIENT_MAPPER] Matched caller_number prefix: {prefix} -> {client_id}")
            return client_id
    
    return None


def get_client_id_from_destination_number(destination_number: Optional[str]) -> Optional[str]:
    """
    着信番号から client_id を取得
    
    :param destination_number: 着信番号（例: "05058304073"）
    :return: client_id または None
    """
    if not destination_number:
        return None
    
    mapping = load_client_mapping()
    dest_mappings = mapping.get("mappings", {}).get("by_destination_number", {})
    
    # 完全一致またはプレフィックスマッチング
    if destination_number in dest_mappings:
        client_id = dest_mappings[destination_number]
        logger.debug(f"[CLIENT_MAPPER] Matched destination_number: {destination_number} -> {client_id}")
        return client_id
    
    # プレフィックスマッチング
    for prefix, client_id in dest_mappings.items():
        if destination_number.startswith(prefix):
            logger.debug(f"[CLIENT_MAPPER] Matched destination_number prefix: {prefix} -> {client_id}")
            return client_id
    
    return None


def get_client_id_from_sip_header(sip_headers: Optional[dict]) -> Optional[str]:
    """
    SIPヘッダから client_id を取得（将来実装）
    
    :param sip_headers: SIPヘッダ（dict）
    :return: client_id または None
    """
    if not sip_headers:
        return None
    
    mapping = load_client_mapping()
    header_mappings = mapping.get("mappings", {}).get("by_sip_header", {})
    
    # X-Liberty-Client ヘッダをチェック
    for header_name, header_key in header_mappings.items():
        if header_name in sip_headers:
            client_id = sip_headers[header_name]
            logger.debug(f"[CLIENT_MAPPER] Matched SIP header: {header_name}={client_id}")
            return client_id
    
    return None


def resolve_client_id(
    caller_number: Optional[str] = None,
    destination_number: Optional[str] = None,
    sip_headers: Optional[dict] = None,
    fallback: Optional[str] = None
) -> str:
    """
    複数の情報源から client_id を解決する（優先順位順）
    
    :param caller_number: 発信者番号
    :param destination_number: 着信番号
    :param sip_headers: SIPヘッダ
    :param fallback: フォールバック用の client_id
    :return: 解決された client_id
    """
    # 優先順位: SIPヘッダ > 着信番号 > 発信者番号 > フォールバック > デフォルト
    client_id = None
    
    # 1. SIPヘッダから取得
    if sip_headers:
        client_id = get_client_id_from_sip_header(sip_headers)
        if client_id:
            logger.info(f"[CLIENT_MAPPER] Resolved from SIP header: {client_id}")
            return client_id
    
    # 2. 着信番号から取得
    if destination_number:
        client_id = get_client_id_from_destination_number(destination_number)
        if client_id:
            logger.info(f"[CLIENT_MAPPER] Resolved from destination_number: {destination_number} -> {client_id}")
            return client_id
    
    # 3. 発信者番号から取得
    if caller_number:
        client_id = get_client_id_from_caller_number(caller_number)
        if client_id:
            logger.info(f"[CLIENT_MAPPER] Resolved from caller_number: {caller_number} -> {client_id}")
            return client_id
    
    # 4. フォールバック
    if fallback:
        logger.info(f"[CLIENT_MAPPER] Using fallback: {fallback}")
        return fallback
    
    # 5. デフォルト
    mapping = load_client_mapping()
    default_client_id = mapping.get("default_client_id", "000")
    logger.info(f"[CLIENT_MAPPER] Using default: {default_client_id}")
    return default_client_id


def clear_mapping_cache() -> None:
    """
    マッピングキャッシュをクリア（ホットリロード用）
    """
    global _mapping_cache, _mapping_cache_path
    _mapping_cache = None
    _mapping_cache_path = None
    logger.debug("[CLIENT_MAPPER] Cache cleared")

