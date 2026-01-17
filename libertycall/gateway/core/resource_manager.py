"""Resource cleanup helpers extracted from AICore."""

from __future__ import annotations


def cleanup_asr_instance(core, call_id: str) -> None:
    if not hasattr(core, "asr_instances"):
        return

    if call_id in core.asr_instances:
        print(f"[ASR_CLEANUP_START] call_id={call_id}", flush=True)
        core.logger.info("[ASR_CLEANUP_START] call_id=%s", call_id)
        try:
            asr = core.asr_instances[call_id]
            if hasattr(asr, "end_stream"):
                asr.end_stream(call_id)
            elif hasattr(asr, "stop"):
                asr.stop()
            del core.asr_instances[call_id]
            print(f"[ASR_CLEANUP_DONE] call_id={call_id}, remaining={len(core.asr_instances)}", flush=True)
            core.logger.info(
                "[ASR_CLEANUP_DONE] call_id=%s, remaining=%s",
                call_id,
                len(core.asr_instances),
            )
        except Exception as exc:
            core.logger.error(
                "[ASR_CLEANUP_ERROR] call_id=%s: %s",
                call_id,
                exc,
                exc_info=True,
            )
            print(f"[ASR_CLEANUP_ERROR] call_id={call_id}: {exc}", flush=True)
    else:
        core.logger.debug("[ASR_CLEANUP_SKIP] No ASR instance for call_id=%s", call_id)


def cleanup_call(core, call_id: str) -> None:
    try:
        try:
            core._call_started_calls.discard(call_id)
        except Exception:
            pass
        try:
            core._intro_played_calls.discard(call_id)
        except Exception:
            pass

        dict_names = [
            "last_activity",
            "is_playing",
            "partial_transcripts",
            "last_template_play",
            "session_info",
            "last_ai_templates",
        ]

        try:
            uuid = None
            try:
                if hasattr(core, "call_uuid_map") and isinstance(core.call_uuid_map, dict):
                    uuid = core.call_uuid_map.get(call_id) or uuid
            except Exception:
                pass
            try:
                if not uuid and hasattr(core, "call_client_map") and isinstance(core.call_client_map, dict):
                    uuid = getattr(core, "call_uuid_by_call_id", {}).get(call_id) or uuid
            except Exception:
                pass
            try:
                if not uuid and hasattr(core, "_call_uuid_map") and isinstance(core._call_uuid_map, dict):
                    uuid = core._call_uuid_map.get(call_id) or uuid
            except Exception:
                pass

            if uuid:
                core.logger.info(
                    "[CLEANUP] Sending uuid_break/uuid_kill to FreeSWITCH for uuid=%s call_id=%s",
                    uuid,
                    call_id,
                )
                import subprocess

                fs_cli_paths = [
                    "/usr/local/freeswitch/bin/fs_cli",
                    "/usr/bin/fs_cli",
                    "/usr/local/bin/fs_cli",
                ]
                executed = False
                for fs_cli in fs_cli_paths:
                    try:
                        subprocess.run(
                            [fs_cli, "-x", f"uuid_break {uuid} all"],
                            timeout=2,
                            capture_output=True,
                        )
                        subprocess.run(
                            [fs_cli, "-x", f"uuid_kill {uuid}"],
                            timeout=2,
                            capture_output=True,
                        )
                        executed = True
                        core.logger.info(
                            "[CLEANUP] fs_cli executed at %s for uuid=%s",
                            fs_cli,
                            uuid,
                        )
                        break
                    except FileNotFoundError:
                        continue
                    except Exception as exc:
                        core.logger.warning(
                            "[CLEANUP] fs_cli call failed (%s) for uuid=%s: %s",
                            fs_cli,
                            uuid,
                            exc,
                        )
                if not executed:
                    try:
                        subprocess.run(
                            ["fs_cli", "-x", f"uuid_break {uuid} all"],
                            timeout=2,
                            capture_output=True,
                        )
                        subprocess.run(
                            ["fs_cli", "-x", f"uuid_kill {uuid}"],
                            timeout=2,
                            capture_output=True,
                        )
                        core.logger.info("[CLEANUP] fs_cli executed via PATH for uuid=%s", uuid)
                    except Exception as exc:
                        core.logger.error(
                            "[CLEANUP] Could not execute fs_cli for uuid=%s: %s",
                            uuid,
                            exc,
                        )
        except Exception as exc:
            core.logger.debug(
                "[CLEANUP] FreeSWITCH stop attempt failed for call_id=%s: %s",
                call_id,
                exc,
            )

        for name in dict_names:
            try:
                d = getattr(core, name, None)
                if isinstance(d, dict) and call_id in d:
                    del d[call_id]
                    core.logger.info("[CLEANUP] Removed %s entry for call_id=%s", name, call_id)
            except Exception as exc:
                core.logger.debug("[CLEANUP] Could not remove %s for %s: %s", name, call_id, exc)

        try:
            if hasattr(core, "flow_engines") and isinstance(core.flow_engines, dict):
                if call_id in core.flow_engines:
                    del core.flow_engines[call_id]
                    core.logger.info("[CLEANUP] Removed flow_engine instance for call_id=%s", call_id)
        except Exception:
            pass

        try:
            for qname in ("tts_queue", "audio_output_queue", "tts_out_queue"):
                q = getattr(core, qname, None)
                if q is not None:
                    try:
                        while not q.empty():
                            q.get_nowait()
                        core.logger.info("[CLEANUP] Cleared queue %s for call_id=%s", qname, call_id)
                    except Exception:
                        core.logger.debug("[CLEANUP] Failed clearing queue %s for call_id=%s", qname, call_id)
        except Exception:
            pass

        try:
            if hasattr(core, "asr_instances") and isinstance(core.asr_instances, dict):
                asr = core.asr_instances.get(call_id)
                if asr:
                    if hasattr(asr, "_queue"):
                        try:
                            while not asr._queue.empty():
                                asr._queue.get_nowait()
                            core.logger.info("[CLEANUP] Flushed ASR queue for %s", call_id)
                        except Exception:
                            core.logger.debug("[CLEANUP] Failed flushing ASR queue for %s", call_id)
                    try:
                        if hasattr(asr, "stop"):
                            asr.stop()
                        elif hasattr(asr, "close"):
                            asr.close()
                        core.logger.info("[CLEANUP] Stopped ASR instance for %s", call_id)
                    except Exception:
                        core.logger.debug("[CLEANUP] Could not stop ASR instance for %s", call_id)
                    try:
                        del core.asr_instances[call_id]
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            if hasattr(core, "_auto_hangup_timers") and isinstance(core._auto_hangup_timers, dict):
                t = core._auto_hangup_timers.pop(call_id, None)
                if t is not None:
                    try:
                        t.cancel()
                    except Exception:
                        pass
                    core.logger.info("[CLEANUP] Cancelled auto_hangup timer for %s", call_id)
        except Exception:
            pass

        try:
            if hasattr(core, "reset_call"):
                core.reset_call(call_id)
                core.logger.info("[CLEANUP] reset_call() invoked for call_id=%s", call_id)
        except Exception as exc:
            core.logger.debug("[CLEANUP] reset_call error for %s: %s", call_id, exc)
    except Exception as exc:
        core.logger.exception(
            "[CLEANUP] Unexpected error during cleanup_call for %s: %s",
            call_id,
            exc,
        )
