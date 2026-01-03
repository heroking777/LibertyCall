#!/usr/bin/env bash
set -u

SID="${1:-}"
CID="${2:-}"
OUTFILE="/tmp/call_uuid_${SID}.txt"

TIMEOUT_SEC="${TIMEOUT_SEC:-30}"
SLEEP_SEC="${SLEEP_SEC:-1}"
TIME_WINDOW_SEC="${TIME_WINDOW_SEC:-45}"
channels=""
REASON="init"
MATCH_STRATEGY="init"
NONE_CAUSE=""
UUID_FOUND=""
attempt=0
DIAG_FLAG="${DIAG:-0}"
CALLID_ATTEMPTED=0
TIMEWINDOW_ATTEMPTED=0
EXT_ATTEMPTED=0
LATEST_ATTEMPTED=0

mkdir -p /tmp >/dev/null 2>&1 || true
touch "${OUTFILE}"
DIAG_LOG="/tmp/track_uuid_diag_${SID}.log"
: > "${DIAG_LOG}"

# ---- DIAG: always capture stderr + crash reason into OUTFILE ----
set +e
set +o pipefail 2>/dev/null || true

exec 2>>"${DIAG_LOG}"
echo "DIAG_STDERR_REDIRECTED_AT=$(date -Is)" >>"${OUTFILE}"
echo "DIAG_LOG=${DIAG_LOG}" >>"${OUTFILE}"

set -E
trap 'rc=$?; echo "DIAG_ERR_AT_LINE=${LINENO} RC=${rc}" >>"${OUTFILE}"; exit ${rc}' ERR
trap 'rc=$?;
  last_cmd="${DIAG_LAST_CMD:-${BASH_COMMAND:-}}";
  last_lineno="${DIAG_LAST_LINENO:-${LINENO:-}}";
  echo "DIAG_EXIT_RC=${rc} AT=$(date -Is)" >>"${OUTFILE}";
  echo "DIAG_LAST_CMD=${last_cmd}" >>"${OUTFILE}";
  echo "DIAG_LAST_LINENO=${last_lineno}" >>"${OUTFILE}";
' EXIT

# ---- DIAG: xtrace with line numbers (only when DIAG=1) ----
if [[ "${DIAG_FLAG}" == "1" ]]; then
  export PS4='+LINE ${LINENO}: '
  BASH_XTRACEFD=2
  set -x
  trap 'DIAG_LAST_CMD="${BASH_COMMAND}"; DIAG_LAST_LINENO="${LINENO}"' DEBUG
fi

has_key() {
  grep -q "^$1=" "${OUTFILE}" 2>/dev/null || false
}

set_kv() {
  local key="$1" val="$2"
  echo "${key}=${val}" >> "${OUTFILE}"
}

maybe_write_session_info() {
  has_key "SESSION_ID" || echo "SESSION_ID=${SID}" >>"${OUTFILE}"
  has_key "TARGET_CALLID" || echo "TARGET_CALLID=${CID}" >>"${OUTFILE}"
}

write_diag() {
  local line="$1"
  if [[ "${DIAG_FLAG}" == "1" ]]; then
    echo "${line}" >>"${OUTFILE}"
  fi
}

mark_attempt() {
  local strat="$1" status="$2" detail="${3:-}"
  local val="${status}"
  if [[ -n "${detail}" ]]; then
    val="${val}:${detail}"
  fi
  set_kv "ATTEMPT_${strat}" "${val}"
}

record_candidate_summary() {
  local prefix="$1"
  local list="${2:-}"
  local cleaned=""
  if [[ -n "${list}" ]]; then
    cleaned="$(printf '%s\n' "${list}" | sed '/^$/d')"
  fi
  local cnt="0"
  if [[ -n "${cleaned}" ]]; then
    cnt="$(printf '%s\n' "${cleaned}" | wc -l | tr -d ' ')"
  fi
  set_kv "${prefix}_CAND_CNT" "${cnt}"
  local top3=""
  if [[ -n "${cleaned}" ]]; then
    top3="$(printf '%s\n' "${cleaned}" | head -n 3 | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
  fi
  set_kv "${prefix}_CAND_TOP3" "${top3}"
  eval "${prefix}_CAND_CNT_VAL=\"${cnt}\""
  eval "${prefix}_CAND_TOP3_VAL=\"${top3}\""
}

is_valid_uuid() {
  local val="$1"
  [[ "${val}" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]
}

write_uuid_line() {
  local uuid_val="$1"
  set_kv "UUID" "${uuid_val}"
  if [[ "${uuid_val}" != "none" ]]; then
    set_kv "UUID_FOUND_AT" "$(date -Is)"
  fi
}

pick_uuid_by_sip_call_id() {
  local target_callid="${1:-}"
  local channels_csv="${2:-}"
  local remote_ip="${3:-}"

  local cand
  local mismatch_c=0
  if [[ "${DIAG_FLAG}" == "1" ]]; then
    printf '%s\n' "${channels_csv}" \
      | awk -F',' -v rip="${remote_ip}" '
          NR==1 { next }
          $2=="inbound" && $5 ~ /^sofia\/external\// {
            if (rip != "" && $9 != rip) next
            print "DIAG_CAND_IP=" $1 "," $9 "," $5
            c++; if (c>=3) exit
          }
        ' \
      >> "${OUTFILE}"
  fi

  cand="$(printf '%s\n' "${channels_csv}" \
    | awk -F',' -v rip="${remote_ip}" '
        NR==1 { next }
        $2=="inbound" && $5 ~ /^sofia\/external\// {
          if (rip != "" && $9 != rip) next
          print $1 "," $4
        }
      ' \
    | sort -t, -k2,2nr \
    | head -n 5 \
    | cut -d, -f1
  )"

  record_candidate_summary "CALLID" "${cand}"
  mark_attempt "CALLID" "cand" "cnt=${CALLID_CAND_CNT_VAL:-0}"

  [[ -z "${cand}" ]] && mark_attempt "CALLID" "fail" "reason=no_candidates" && return 1

  local u v
  while IFS= read -r u; do
    [[ -z "${u}" ]] && continue

    v="$(fs_cli -x "uuid_getvar ${u} sip_call_id" 2>/dev/null | tr -d '\r' || true)"
    if [[ "${v}" == +OK* ]]; then
      v="${v#+OK }"
    elif [[ "${v}" == -ERR* ]]; then
      v=""
    fi
    if [[ -n "${v}" ]]; then
      write_diag "DIAG_UUID_VAR_sip_call_id_${u}=${v}"
    fi
    if [[ -n "${v}" && "${v}" == "${target_callid}" ]]; then
      echo "${u}"
      mark_attempt "CALLID" "ok" "uuid=${u}"
      return 0
    fi

    v="$(fs_cli -x "uuid_getvar ${u} variable_sip_call_id" 2>/dev/null | tr -d '\r' || true)"
    if [[ "${v}" == +OK* ]]; then
      v="${v#+OK }"
    elif [[ "${v}" == -ERR* ]]; then
      v=""
    fi
    if [[ -n "${v}" ]]; then
      write_diag "DIAG_UUID_VAR_variable_sip_call_id_${u}=${v}"
    fi
    if [[ -n "${v}" && "${v}" == "${target_callid}" ]]; then
      echo "${u}"
      mark_attempt "CALLID" "ok" "uuid=${u}"
      return 0
    fi

    if [[ -n "${v}" && "${DIAG_FLAG}" == "1" && "${mismatch_c}" -lt 3 ]]; then
      write_diag "DIAG_CALLID_MISMATCH_${u}=var:${v} target:${target_callid}"
      mismatch_c=$((mismatch_c+1))
    fi
  done <<< "${cand}"

  mark_attempt "CALLID" "fail" "reason=no_match"
  return 1
}

pick_uuid_by_timewindow() {
  local channels_csv="$1"
  local start_epoch="$2"

  [[ -z "${start_epoch}" ]] && return 1

  printf '%s\n' "${channels_csv}" | awk -F',' -v se="${start_epoch}" '
    NR==1 { next }
    $2!="inbound" { next }
    $5 !~ /^sofia\/external\// && $5 !~ /^sofia\/gateway\// { next }
    {
      ce = $4 + 0
      d = ce - se
      if (d < 0) d = -d
      if (best == "" || d < bestd) { best=$0; bestd=d }
    }
    END {
      if (best != "") {
        print best
        print "DIFF_SEC=" bestd
      }
    }
  '
}

SIP_LOG="/tmp/call_uuid_track_${SID}.log"
SIP_FILE="$(grep -m1 '^UUID_TRACK_SIP=' "${SIP_LOG}" 2>/dev/null | cut -d= -f2- || true)"
UUID_TRACK_START_AT="$(grep -m1 '^UUID_TRACK_START=' "${SIP_LOG}" 2>/dev/null | cut -d= -f2- || true)"
SIP_TS="$(basename "${SIP_FILE}" 2>/dev/null | sed -nE 's/^sip_cap_([0-9]{8}_[0-9]{6}).*/\1/p')"
START_EPOCH=""
if [[ -n "${SIP_TS}" ]]; then
  START_EPOCH="$(date -d "${SIP_TS:0:8} ${SIP_TS:9:2}:${SIP_TS:11:2}:${SIP_TS:13:2}" +%s 2>/dev/null || true)"
fi
if [[ -z "${START_EPOCH}" && -n "${UUID_TRACK_START_AT}" ]]; then
  START_EPOCH="$(date -d "${UUID_TRACK_START_AT}" +%s 2>/dev/null || true)"
fi
set_kv "UUID_TRACK_START_AT" "${UUID_TRACK_START_AT}"
set_kv "SIP_TS" "${SIP_TS}"
set_kv "START_EPOCH" "${START_EPOCH}"
set_kv "TIME_WINDOW_SEC" "${TIME_WINDOW_SEC}"
echo "SIP_FILE=${SIP_FILE}" >>"${OUTFILE}"

EXT=""

SIP_KEY_EXT_FOR_MATCH=""

if [[ -n "${SIP_FILE}" && -f "${SIP_FILE}" ]]; then
  SIP_KEY_CALLID="$(awk 'BEGIN{IGNORECASE=1} /^[[:space:]]*Call-ID:/{sub(/.*Call-ID:[[:space:]]*/,""); gsub(/\r$/,""); print; exit}' "${SIP_FILE}" 2>/dev/null || true)"
  SIP_KEY_TO="$(awk 'BEGIN{IGNORECASE=1} /^[[:space:]]*(To:|t:)/{gsub(/\r$/,""); print; exit}' "${SIP_FILE}" 2>/dev/null || true)"
  SIP_KEY_FROM="$(awk 'BEGIN{IGNORECASE=1} /^[[:space:]]*From:/{gsub(/\r$/,""); print; exit}' "${SIP_FILE}" 2>/dev/null || true)"
  SIP_KEY_CONTACT="$(awk 'BEGIN{IGNORECASE=1} /^[[:space:]]*Contact:/{gsub(/\r$/,""); print; exit}' "${SIP_FILE}" 2>/dev/null || true)"
  SIP_KEY_RECEIVED="$(awk 'BEGIN{IGNORECASE=1} /^[[:space:]]*Received:/{gsub(/\r$/,""); print; exit}' "${SIP_FILE}" 2>/dev/null || true)"
  echo "SIP_KEY_CALLID=${SIP_KEY_CALLID}" >>"${OUTFILE}"
  echo "SIP_KEY_TO=${SIP_KEY_TO}" >>"${OUTFILE}"
  echo "SIP_KEY_FROM=${SIP_KEY_FROM}" >>"${OUTFILE}"
  echo "SIP_KEY_CONTACT=${SIP_KEY_CONTACT}" >>"${OUTFILE}"
  echo "SIP_KEY_RECEIVED=${SIP_KEY_RECEIVED}" >>"${OUTFILE}"
  pick_ext() {
    printf '%s\n' "${SIP_KEY_FROM}" "${SIP_KEY_CONTACT}" "${SIP_KEY_TO}" \
      | sed -nE 's/.*sip:([0-9]{2,4})@.*/\1/p' \
      | head -n 1
  }
  EXT="$(pick_ext)"
  SIP_KEY_EXT_FOR_MATCH="${EXT}"
  echo "SIP_KEY_EXT=${EXT}" >>"${OUTFILE}"
  write_diag "DIAG_EXT=${EXT}"
  REMOTE_NUM="$(printf '%s\n' "${SIP_KEY_TO}" | sed -nE 's/.*sip:([0-9]{6,})@.*/\1/p' | head -n 1)"
  REMOTE_IP="$(awk '
    match($0, /IP[[:space:]]+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)\.[0-9]+[[:space:]]*>/, m) { print m[1]; exit }
  ' "${SIP_FILE}" 2>/dev/null || true)"
  echo "SIP_KEY_REMOTE_NUM=${REMOTE_NUM}" >>"${OUTFILE}"
  echo "SIP_REMOTE_IP=${REMOTE_IP}" >>"${OUTFILE}"
  if [[ "${DIAG_FLAG}" == "1" ]]; then
    awk 'BEGIN{IGNORECASE=1}
      /^(Received:|X-Received:|Via:|Contact:)/{
        gsub(/\r$/,""); print "DIAG_SIP_IP_SRC=" $0; c++; if (c>=3) exit
      }
    ' "${SIP_FILE}" >>"${OUTFILE}"
  fi
fi

append_footer_and_exit() {
  maybe_write_session_info
  # normalize final vars (never empty)
  REASON="${REASON:-unknown}"
  MATCH_STRATEGY="${MATCH_STRATEGY:-unknown}"
  set_kv "REASON" "${REASON}"
  set_kv "MATCH_STRATEGY" "${MATCH_STRATEGY:-${REASON}}"
  {
    echo "TIMEOUT_SEC=${TIMEOUT_SEC}"
    printf '%s\n' "${channels}" | tail -n 20 | sed 's/\r//g' | awk '{print "CH_LAST20=" $0}'
    echo "UUID_PHASE=tracker_done"
    echo "UUID_TRACK_END_AT=$(date -Is)"
  } >>"${OUTFILE}"
  set_kv "FINAL_REASON" "${REASON:-unknown}"
  set_kv "FINAL_MATCH_STRATEGY" "${MATCH_STRATEGY:-${REASON:-unknown}}"
  exit 0
}

if [[ -z "${SID}" || -z "${CID}" || "${CID}" == "none" ]]; then
  REASON="missing_args"
  MATCH_STRATEGY="missing_args"
  NONE_CAUSE="${REASON}"
  write_uuid_line "none"
  append_footer_and_exit
  exit 0
fi

if ! command -v fs_cli >/dev/null 2>&1; then
  REASON="fs_cli_missing"
  MATCH_STRATEGY="fs_cli_missing"
  NONE_CAUSE="${REASON}"
  write_uuid_line "none"
  append_footer_and_exit
fi

REASON="ext_not_found_in_channels"
MATCH_STRATEGY="ext_not_found_in_channels"
for attempt in $(seq 1 "${TIMEOUT_SEC}"); do
  channels="$(fs_cli -x 'show channels' 2>/dev/null || true)"

  if [[ "${DIAG_FLAG}" == "1" ]]; then
    if [[ -n "${EXT}" ]]; then
      printf '%s\n' "${channels}" \
        | awk -F',' -v ext="${EXT}" '
            NR==1 { next }
            ($29==ext || $5 ~ ("sofia/external/" ext "@")) { print; c++; if (c>=3) exit }
          ' \
        | sed 's/^/DIAG_CH_MATCH=/' >> "${OUTFILE}"
    fi

    printf '%s\n' "${channels}" \
      | awk -F',' '
          NR==1 { next }
          $2=="inbound" && $5 ~ /^sofia\/external\// { print; c++; if (c>=3) exit }
        ' \
      | sed 's/^/DIAG_CH_INBOUND_EXT_TOP3=/' >> "${OUTFILE}"
  fi

  if [[ -z "${EXT}" ]]; then
    EXT="$(printf '%s\n' "${channels}" | awk -F',' '
      NR==1 { next }
      $2=="inbound" && $5 ~ /sofia\/external\// {
        split($5, parts, "/")
        split(parts[3], addr, "@")
        if (addr[1] ~ /^[0-9]+$/) { print addr[1]; exit }
      }
    ')"
    [[ -n "${EXT}" ]] && echo "SIP_KEY_EXT_FALLBACK=${EXT}" >>"${OUTFILE}"
  fi

  UUID_FOUND_CALLID=""
  if [[ -n "${SIP_KEY_CALLID}" ]]; then
    mark_attempt "CALLID" "start"
    UUID_FOUND_CALLID="$(pick_uuid_by_sip_call_id "${SIP_KEY_CALLID}" "${channels}" || true)"
  else
    record_candidate_summary "CALLID" ""
    mark_attempt "CALLID" "fail" "reason=no_callid_in_sip"
  fi
  if [[ -n "${UUID_FOUND_CALLID}" ]]; then
    if is_valid_uuid "${UUID_FOUND_CALLID}"; then
      UUID_FOUND="${UUID_FOUND_CALLID}"
      set_kv "CH_PICKED_CALLID_UUID" "${UUID_FOUND_CALLID}"
      REASON="${REASON:-ok_by_sip_call_id}"
      MATCH_STRATEGY="${MATCH_STRATEGY:-ok_by_sip_call_id}"
      break
    else
      UUID_FOUND_CALLID=""
      mark_attempt "CALLID" "fail" "reason=invalid_uuid"
    fi
  fi

  CH_PICKED_TIME_RAW=""
  CH_PICKED_TIME=""
  TIMEWINDOW_DIFF=""
  if [[ -n "${START_EPOCH}" ]]; then
    mark_attempt "TIMEWINDOW" "start"
    timewindow_candidates="$(printf '%s\n' "${channels}" | awk -F',' '
      NR==1 { next }
      $2=="inbound" && $5 ~ /^sofia\/external\// { print $1 }
    ')"
    record_candidate_summary "TIMEWINDOW" "${timewindow_candidates}"
    mark_attempt "TIMEWINDOW" "cand" "cnt=${TIMEWINDOW_CAND_CNT_VAL:-0}"
    CH_PICKED_TIME_RAW="$(pick_uuid_by_timewindow "${channels}" "${START_EPOCH}" || true)"
    CH_PICKED_TIME="$(printf '%s\n' "${CH_PICKED_TIME_RAW}" | head -n 1)"
    TIMEWINDOW_DIFF="$(printf '%s\n' "${CH_PICKED_TIME_RAW}" | sed -nE 's/^DIFF_SEC=([0-9]+).*/\1/p')"
    [[ -n "${TIMEWINDOW_DIFF}" ]] && set_kv "TIMEWINDOW_DIFF_SEC" "${TIMEWINDOW_DIFF}"
  else
    record_candidate_summary "TIMEWINDOW" ""
    mark_attempt "TIMEWINDOW" "fail" "reason=no_start_epoch"
  fi
  if [[ -n "${CH_PICKED_TIME}" ]]; then
    UUID_FOUND="$(printf '%s\n' "${CH_PICKED_TIME}" | awk -F',' '{print $1}')"
    if [[ -n "${UUID_FOUND}" ]] && is_valid_uuid "${UUID_FOUND}"; then
      set_kv "CH_PICKED_TIME" "${CH_PICKED_TIME}"
      if [[ -n "${TIMEWINDOW_DIFF}" && "${TIMEWINDOW_DIFF}" -le "${TIME_WINDOW_SEC}" ]]; then
        MATCH_STRATEGY="${MATCH_STRATEGY:-ok_by_timewindow_nearest}"
        REASON="${REASON:-ok_by_timewindow_nearest}"
        mark_attempt "TIMEWINDOW" "ok" "uuid=${UUID_FOUND};diff=${TIMEWINDOW_DIFF}"
        break
      else
        set_kv "TIMEWINDOW_TOO_FAR" "1"
        REASON="timewindow_too_far"
        MATCH_STRATEGY="timewindow_too_far"
        mark_attempt "TIMEWINDOW" "fail" "reason=diff_gt_window;diff=${TIMEWINDOW_DIFF}"
      fi
    else
      UUID_FOUND=""
    fi
  else
    if [[ -n "${START_EPOCH}" ]]; then
      if [[ "${TIMEWINDOW_CAND_CNT_VAL:-0}" == "0" ]]; then
        mark_attempt "TIMEWINDOW" "fail" "reason=no_candidates"
      else
        mark_attempt "TIMEWINDOW" "fail" "reason=invalid_pick"
      fi
    fi
  fi

  if [[ -n "${SIP_KEY_EXT_FOR_MATCH}" ]]; then
    mark_attempt "EXT" "start"
    EXT_CAND_LIST="$(printf '%s\n' "${channels}" | awk -F',' -v ext="${SIP_KEY_EXT_FOR_MATCH}" '
      NR==1 { next }
      $2 != "inbound" { next }
      {
        ok = 0
        if (ext != "" && $29 == ext) ok = 1
        if (ext != "" && $5 ~ ("sofia/external/" ext "@")) ok = 1
        if (ok == 1) print $1
      }
    ')"
    record_candidate_summary "EXT" "${EXT_CAND_LIST}"
    mark_attempt "EXT" "cand" "cnt=${EXT_CAND_CNT_VAL:-0}"
    CH_PICKED_EXT="$(printf '%s\n' "${channels}" | awk -F',' -v ext="${SIP_KEY_EXT_FOR_MATCH}" '
      NR==1 { next }
      $2 != "inbound" { next }
      {
        ok = 0
        if (ext != "" && $29 == ext) ok = 1
        if (ext != "" && $5 ~ ("sofia/external/" ext "@")) ok = 1
        if (ok == 1) {
          ce = $4 + 0
          if (ce > max) { max = ce; line = $0 }
        }
      }
      END { if (line != "") print line }
    ')"
    if [[ -n "${CH_PICKED_EXT}" ]]; then
      UUID_FOUND="$(printf '%s\n' "${CH_PICKED_EXT}" | awk -F',' '{print $1}')"
      if [[ -n "${UUID_FOUND}" ]] && is_valid_uuid "${UUID_FOUND}"; then
        set_kv "CH_PICKED_EXT" "${CH_PICKED_EXT}"
        REASON="${REASON:-ok_by_ext_match}"
        MATCH_STRATEGY="${MATCH_STRATEGY:-ok_by_ext_match}"
        mark_attempt "EXT" "ok" "uuid=${UUID_FOUND}"
        break
      else
        UUID_FOUND=""
      fi
    else
      REASON="ext_not_found_in_channels"
      MATCH_STRATEGY="ext_not_found_in_channels"
      mark_attempt "EXT" "fail" "reason=no_match"
    fi
  else
    REASON="ext_missing_from_sip"
    MATCH_STRATEGY="ext_missing_from_sip"
    record_candidate_summary "EXT" ""
    mark_attempt "EXT" "fail" "reason=no_ext_from_sip"
  fi

  if [[ -z "${UUID_FOUND}" ]]; then
    mark_attempt "LATEST" "start"
    LATEST_CAND_LIST="$(printf '%s\n' "${channels}" | awk -F',' '
      NR==1 { next }
      $2 == "inbound" && $5 ~ /^sofia\/external\// { print $1 }
    ')"
    record_candidate_summary "LATEST" "${LATEST_CAND_LIST}"
    mark_attempt "LATEST" "cand" "cnt=${LATEST_CAND_CNT_VAL:-0}"
    CH_PICKED="$(printf '%s\n' "${channels}" | awk -F',' '
      NR==1 { next }
      $2 != "inbound" { next }
      $5 !~ /^sofia\/external\// { next }
      {
        ce = $4 + 0
        if (ce > max) { max = ce; line = $0; u = $1 }
      }
      END { if (line != "") print line }
    ')"
    if [[ -n "${CH_PICKED}" ]]; then
      UUID_FOUND="$(printf '%s\n' "${CH_PICKED}" | awk -F',' '{print $1}')"
      if [[ -n "${UUID_FOUND}" ]] && is_valid_uuid "${UUID_FOUND}"; then
        set_kv "CH_PICKED" "${CH_PICKED}"
        REASON="${REASON:-ok_by_latest_inbound_external}"
        MATCH_STRATEGY="${MATCH_STRATEGY:-ok_by_latest_inbound_external}"
        mark_attempt "LATEST" "ok" "uuid=${UUID_FOUND}"
        break
      else
        UUID_FOUND=""
      fi
    else
      REASON="no_inbound_external_in_channels"
      MATCH_STRATEGY="no_inbound_external_in_channels"
      mark_attempt "LATEST" "fail" "reason=no_candidates"
    fi
  fi

  sleep "${SLEEP_SEC}"
done

if [[ -n "${UUID_FOUND}" ]]; then
  write_uuid_line "${UUID_FOUND}"
else
  NONE_CAUSE="${REASON}"
  write_uuid_line "none"
fi

REASON="${REASON:-unknown}"
append_footer_and_exit
