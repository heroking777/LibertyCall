#!/usr/bin/env python3

import subprocess
import sys
import logging
import os

LOG_PATH = "/opt/libertycall/logs/hangup_call.log"

# ログディレクトリを作成
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# ファイルとコンソール（journalctl）の両方に出力
logger = logging.getLogger("hangup_call")
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
    logging.Formatter("[HANGUP_CALL] %(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

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

def _find_trunk_channel(call_id: str | None = None) -> str | None:
    """
    `core show channels concise` の結果から
    PJSIP/trunk-rakuten-in-* のチャネルを 1 本だけ拾う。
    call_id が指定されている場合は、その call_id を含むチャネルを優先的に探す。
    """
    logger.info("FIND_TRUNK_CHANNEL: searching for PJSIP/trunk-rakuten-in-* call_id=%s", call_id or "NONE")
    out = _run_cmd(["/usr/sbin/asterisk", "-rx", "core show channels concise"])
    if not out:
        logger.warning("FIND_TRUNK_CHANNEL: no output from asterisk command")
        return None

    # concise 形式: Channel!Context!Exten!Priority!State!Application!Data!...
    # call_id が指定されている場合は、その call_id を含むチャネルを優先的に探す
    if call_id:
        for line in out.strip().splitlines():
            if f"PJSIP/trunk-rakuten-in-{call_id}" in line:
                parts = line.split("!")
                if not parts:
                    continue
                chan = parts[0].strip()
                if chan:
                    logger.info("FIND_TRUNK_CHANNEL: found channel=%s for call_id=%s", chan, call_id)
                    return chan
    
    # call_id が指定されていない、または一致するチャネルが見つからない場合は、最初に見つかったチャネルを返す
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

def _hangup_channel(channel: str) -> bool:
    logger.info(
        "HANGUP_CHANNEL: channel=%s",
        channel
    )
    # channel hangup の形式: channel request hangup <channel>
    cmd = [
        "/usr/sbin/asterisk",
        "-rx",
        f"channel request hangup {channel}",
    ]
    out = _run_cmd(cmd)
    logger.info("HANGUP_CHANNEL_RESULT: cmd=%s out=%r", " ".join(cmd), out.strip())
    text = out.lower()
    success = "hangup" in text or "success" in text or "requested" in text
    if success:
        logger.info("HANGUP_CHANNEL: success channel=%s", channel)
    else:
        logger.warning("HANGUP_CHANNEL: failed channel=%s out=%r", channel, out.strip())
    return success

def main() -> int:
    call_id = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        logger.info("===== HANGUP_CALL START: call_id=%s =====", call_id or "NONE")
        chan = _find_trunk_channel(call_id) if call_id else _find_trunk_channel()
        if not chan:
            logger.warning("HANGUP_CALL_FAILED: No PJSIP/trunk-rakuten-in channel found for call_id=%s.", call_id or "NONE")
            return 1

        logger.info("HANGUP_CALL: Found trunk channel: %s for call_id=%s", chan, call_id or "NONE")
        ok = _hangup_channel(chan)
        if ok:
            logger.info("HANGUP_CALL_SUCCESS: Hangup OK channel=%s for call_id=%s", chan, call_id or "NONE")
            return 0

        logger.warning("HANGUP_CALL_FAILED: Hangup maybe failed channel=%s for call_id=%s", chan, call_id or "NONE")
        return 1
    except Exception as e:
        logger.exception("HANGUP_CALL_EXCEPTION: main failed error=%r", e)
        return 1

if __name__ == "__main__":
    sys.exit(main())

