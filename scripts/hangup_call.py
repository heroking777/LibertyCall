#!/usr/bin/env python3

import subprocess
import sys
import logging
import os

LOG_PATH = "/opt/libertycall/logs/hangup_call.log"

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logger = logging.getLogger("hangup_call")
logger.setLevel(logging.INFO)

fh = logging.FileHandler(LOG_PATH)
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(fh)
logger.addHandler(logging.StreamHandler(sys.stdout))


def _run_cmd(cmd: list[str]) -> str:
    try:
        logger.info("RUN_CMD: %s", " ".join(cmd))
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            env=os.environ.copy(),
        )
        if res.stderr:
            logger.warning("CMD STDERR: %s", res.stderr.strip())
        logger.info("RUN_CMD_RESULT: stdout=%r", res.stdout.strip())
        return res.stdout
    except Exception as e:
        logger.exception("RUN_CMD_FAILED: cmd=%r error=%r", cmd, e)
        return ""


def _find_channel(call_id: str | None = None) -> str | None:
    cmd = ["sudo", "-u", "asterisk", "/usr/sbin/asterisk", "-rx", "core show channels concise"]
    out = _run_cmd(cmd)
    if not out:
        logger.warning("NO_OUTPUT_FROM_ASTERISK")
        return None
    if call_id:
        for line in out.splitlines():
            if call_id in line:
                chan = line.split("!")[0]
                logger.info("MATCH_BY_CALLID: %s", chan)
                return chan
    for line in out.splitlines():
        if "PJSIP/trunk" in line:
            chan = line.split("!")[0]
            logger.info("MATCH_BY_TRUNK: %s", chan)
            return chan
    logger.warning("NO_CHANNEL_FOUND")
    return None


def _hangup_channel(chan: str):
    cmd = ["sudo", "-u", "asterisk", "/usr/sbin/asterisk", "-rx", f"channel request hangup {chan}"]
    out = _run_cmd(cmd)
    logger.info("HANGUP_RESULT: %s", out.strip())


def main():
    call_id = sys.argv[1] if len(sys.argv) > 1 else None
    logger.info("==== HANGUP_CALL START call_id=%s ====", call_id or "NONE")
    chan = _find_channel(call_id)
    if not chan:
        logger.warning("NO_CHANNEL_FOUND_FOR_CALLID=%s", call_id)
        logger.warning("FALLBACK: hangup all active channels")
        _run_cmd(["sudo", "-u", "asterisk", "/usr/sbin/asterisk", "-rx", "channel request hangup all"])
        return
    _hangup_channel(chan)


if __name__ == "__main__":
    sys.exit(main())
