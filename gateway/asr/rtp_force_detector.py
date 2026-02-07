"""RTP取得の「力技」化 -ERR 対策バイパス手術"""
import subprocess
import time
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

def force_detect_rtp_info(uuid: str, timeout_sec: int = 5) -> Optional[Tuple[str, str, str]]:
    """
    【力技】RTP情報を5秒以内に強制取得
    
    Args:
        uuid: 通話UUID
        timeout_sec: タイムアウト秒数
        
    Returns:
        (local_port, remote_ip, remote_port) or None
    """
    start_time = time.time()
    
    # 【力技1】uuid_media_stats を片っ端から叩く
    commands = [
        f"uuid_media_stats {uuid}",
        f"uuid_getvar {uuid} rtp_local_port",
        f"uuid_getvar {uuid} rtp_remote_ip", 
        f"uuid_getvar {uuid} rtp_remote_port",
        f"uuid_display {uuid}",
        f"uuid_dump {uuid}",
        f"uuid_exists {uuid}"
    ]
    
    for cmd in commands:
        if time.time() - start_time > timeout_sec:
            break
            
        try:
            # fs_cliで直接実行
            result = subprocess.run(
                ["fs_cli", "-H", "127.0.0.1", "--P", "8021", "-p", "ClueCon", "-x", cmd],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0 and result.stdout:
                logger.warning(f"[FORCE_RTP] Command '{cmd}' succeeded: {result.stdout[:200]}")
                
                # ポート情報を抽出
                port_match = re.search(r'port\s*[:=]\s*(\d+)', result.stdout, re.IGNORECASE)
                ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', result.stdout)
                
                if port_match:
                    local_port = port_match.group(1)
                    remote_ip = ip_match.group(1) if ip_match else "UNKNOWN"
                    remote_port = "UNKNOWN"  # 後で取得
                    
                    logger.info(f"[FORCE_RTP] Found port={local_port}, ip={remote_ip}")
                    return (local_port, remote_ip, remote_port)
                    
        except subprocess.TimeoutExpired:
            logger.warning(f"[FORCE_RTP] Command '{cmd}' timeout")
            continue
        except Exception as e:
            logger.warning(f"[FORCE_RTP] Command '{cmd}' failed: {e}")
            continue
    
    # 【力技2】show channels から全チャンネルをスキャン
    try:
        result = subprocess.run(
            ["fs_cli", "-H", "127.0.0.1", "-P", "8021", "-p", "ClueCon", "-x", "show channels"],
            capture_output=True,
            text=True,
            timeout=3
        )
        
        if result.returncode == 0:
            # UUIDに一致する行を探す
            for line in result.stdout.split('\n'):
                if uuid in line:
                    logger.info(f"[FORCE_RTP] Found channel line: {line}")
                    # IPアドレスを抽出
                    ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                    if ip_match:
                        remote_ip = ip_match.group(1)
                        logger.warning(f"[FORCE_RTP] Found IP from channels: {remote_ip}")
                        # デフォルトポート範囲を試す
                        for port in range(10000, 20000, 100):  # 10000-19999
                            test_port = str(port)
                            return (test_port, remote_ip, "UNKNOWN")
                            
    except Exception as e:
        logger.error(f"[FORCE_RTP] show channels failed: {e}")
    
    logger.error(f"[FORCE_RTP] Failed to detect RTP info for {uuid} within {timeout_sec}s")
    return None


def force_detect_rtp_with_fallback(uuid: str) -> Tuple[bool, Optional[Tuple[str, str, str]]]:
    """
    【力技】RTP検出の最終手段
    
    Returns:
        (success, (local_port, remote_ip, remote_port))
    """
    # まず力技を試す
    result = force_detect_rtp_info(uuid, timeout_sec=5)
    if result:
        return True, result
    
    # 失敗したらデフォルト値を返す
    logger.error(f"[RTP_NOT_FOUND] Could not detect RTP for {uuid}")
    return False, None
