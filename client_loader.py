import os
import json
import logging

# クライアントデータのベースパス
BASE_DIR = "/opt/libertycall/clients"

def load_client_profile(client_id):
    """
    client_id (電話番号) に基づき設定をロードする
    """
    target_dir = os.path.join(BASE_DIR, client_id)
    config_path = os.path.join(target_dir, "config.json")
    rules_path = os.path.join(target_dir, "rules.json")

    # フォルダまたは設定が無い場合はエラー
    if not os.path.exists(target_dir):
        raise FileNotFoundError(f"Client directory not found: {client_id}")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    # 1. Config 読込
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 2. Rules 読込
    rules = {}
    if os.path.exists(rules_path):
        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)

    # 3. 音声パスの絶対パス化
    audio_keys = ["greeting_audio", "transfer_audio", "error_audio"]
    for key in audio_keys:
        if key in config and config[key]:
            if not config[key].startswith("/"):
                config[key] = os.path.join(target_dir, config[key])

    # 4. ログディレクトリ設定
    log_dir = os.path.join(target_dir, "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    logging.info(f"[Loader] Loaded profile for {client_id}")

    return {
        "client_id": client_id,
        "base_dir": target_dir,
        "log_dir": log_dir,
        "config": config,
        "rules": rules
    }
