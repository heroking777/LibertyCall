#!/usr/bin/env python3

import subprocess
import sys
import logging
import os

LOG_PATH = "/opt/libertycall/logs/handoff_redirect.log"

# ログディレクトリを作成
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# ファイルとコンソール（journalctl）の両方に出力
logger = logging.getLogger("handoff_redirect")
logger.setLevel(logging.INFO)

# ファイルハンドラ
file_handler = logging.FileHandler(LOG_PATH)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
)

# コンソールハンドラ（journalctl に出力される）
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(
    logging.Formatter("[HANDOFF_REDIRECT] %(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# TODO: 将来的にはクライアントごとに切り替える前提だが、今は 000 固定
HANDOFF_CONTEXT = "handoff-000"
HANDOFF_EXTEN = "1"
HANDOFF_PRIORITY = "1"

def _run_cmd(cmd: list[str]) -> str:
    try:
        logger.info("RUN_CMD: %s", " ".join(cmd))
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if res.stderr:
            logger.warning("CMD STDERR: %s", res.stderr.strip())
        logger.info("RUN_CMD_RESULT: stdout=%r", res.stdout.strip())
        return res.stdout
    except Exception as e:
        logger.exception("RUN_CMD_FAILED: cmd=%r error=%r", cmd, e)
        return ""

def _find_trunk_channel() -> str | None:
    """
    `core show channels concise` の結果から
    PJSIP/trunk-rakuten-in-* のチャネルを 1 本だけ拾う。
    """
    logger.info("FIND_TRUNK_CHANNEL: searching for PJSIP/trunk-rakuten-in-*")
    out = _run_cmd(["/usr/sbin/asterisk", "-rx", "core show channels concise"])
    if not out:
        logger.warning("FIND_TRUNK_CHANNEL: no output from asterisk command")
        return None

    # concise 形式: Channel!Context!Exten!Priority!State!Application!Data!...
    for line in out.strip().splitlines():
        if "PJSIP/trunk-rakuten-in-" not in line:
            continue
        parts = line.split("!")
        if not parts:
            continue
        chan = parts[0].strip()
        if chan:
            logger.info("FIND_TRUNK_CHANNEL: found channel=%s", chan)
            return chan

    logger.warning("FIND_TRUNK_CHANNEL: no matching channel found")
    return None

def _redirect_channel(channel: str) -> bool:
    logger.info(
        "REDIRECT_CHANNEL: channel=%s context=%s exten=%s priority=%s",
        channel,
        HANDOFF_CONTEXT,
        HANDOFF_EXTEN,
        HANDOFF_PRIORITY
    )
    
    # ステップ3: caller_numberを保持（環境変数から取得）
    caller_number = os.getenv("LC_CALLER_NUMBER")
    call_id = os.getenv("LC_CALL_ID")
    if caller_number:
        logger.info("REDIRECT_CHANNEL: preserving caller_number=%s for call_id=%s", caller_number, call_id)
        # Asteriskのchannel変数にcaller_numberを設定（転送先でも保持される）
        set_caller_cmd = [
            "/usr/sbin/asterisk",
            "-rx",
            f"channel set variable {channel} CALLERID(num) {caller_number}",
        ]
        _run_cmd(set_caller_cmd)
        # CALLERID(name)も設定（表示名として使用）
        set_caller_name_cmd = [
            "/usr/sbin/asterisk",
            "-rx",
            f"channel set variable {channel} CALLERID(name) {caller_number}",
        ]
        _run_cmd(set_caller_name_cmd)
    
    # channel redirect の正しい形式: channel redirect <channel> <[[context,]exten,]priority>
    # 例: channel redirect PJSIP/trunk-rakuten-in-000000f2 handoff-000,1,1
    redirect_target = f"{HANDOFF_CONTEXT},{HANDOFF_EXTEN},{HANDOFF_PRIORITY}"
    cmd = [
        "/usr/sbin/asterisk",
        "-rx",
        f"channel redirect {channel} {redirect_target}",
    ]
    out = _run_cmd(cmd)
    logger.info("REDIRECT_CHANNEL_RESULT: cmd=%s out=%r", " ".join(cmd), out.strip())
    text = out.lower()
    success = "redirected" in text or "success" in text
    if success:
        logger.info("REDIRECT_CHANNEL: success channel=%s", channel)
    else:
        logger.warning("REDIRECT_CHANNEL: failed channel=%s out=%r", channel, out.strip())
    return success

def main() -> int:
    try:
        logger.info("===== HANDOFF_REDIRECT START =====")
        chan = _find_trunk_channel()
        if not chan:
            logger.warning("HANDOFF_REDIRECT_FAILED: No PJSIP/trunk-rakuten-in channel found.")
            return 1

        logger.info("HANDOFF_REDIRECT: Found trunk channel: %s", chan)
        ok = _redirect_channel(chan)
        if ok:
            logger.info("HANDOFF_REDIRECT_SUCCESS: Redirect OK channel=%s", chan)
            return 0

        logger.warning("HANDOFF_REDIRECT_FAILED: Redirect maybe failed channel=%s", chan)
        return 1
    except Exception as e:
        logger.exception("HANDOFF_REDIRECT_EXCEPTION: main failed error=%r", e)
        return 1

if __name__ == "__main__":
    sys.exit(main())

