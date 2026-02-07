#!/usr/bin/env bash
set -euo pipefail

# 目的:
# - "FSのlocal_media_portにRTPが到達しているか" を 1回の通話で確定する
# - 通話ごとにlocal_media_portが変わってもズレない方式にする
#
# 使い方:
#   1) 通話前:   sudo timeout 360s /opt/libertycall/scripts/check_rtp_to_local_port.sh capture
#   2) ユーザー: 10秒通話→切断（ここでAIは待たない）
#   3) 通話後:   sudo timeout 60s  /opt/libertycall/scripts/check_rtp_to_local_port.sh analyze
#
# 出力:
# - /tmp/rtp_local_any_*.pcap（広域キャプチャ）
# - /tmp/rtp_local_port_<PORT>_*.pcap（local_media_portに絞ったpcap）
# - packet count（0 / >0 を確定）

MODE="${1:-}"
TS="$(date +%s)"
IFACE="${LC_NET_IFACE:-eth0}"

PCAP_ANY="/tmp/rtp_local_any_${TS}.pcap"
PCAP_ANY_LATEST="/tmp/rtp_local_any_latest.pcap"

get_latest_uuid() {
  # 最新のUUIDを取得（ダイヤルプランで既にUUIDはログに出ている前提）
  # ここではshow channels の最新行からUUIDを拾う（失敗したら空で返す）
  fs_cli -x "show channels" 2>/dev/null | tail -n 5 | awk -F',' '{print $13}' | grep -E '^[0-9a-f-]{36}$' | tail -n 1 || true
}

get_local_media_port() {
  local uuid="$1"
  fs_cli -x "uuid_getvar ${uuid} local_media_port" 2>/dev/null | awk -F'=' '{print $2}' | tr -d ' \r' || true
}

capture_any() {
  echo "== capture_any =="
  echo "ts=${TS} iface=${IFACE}"
  echo "pcap_any=${PCAP_ANY}"
  # FreeSWITCH RTPは広いポートレンジに出るので、まずudp全体からFSホスト宛だけ拾う
  # NOTE: ホスト自身宛RTPのみ想定（外向きRTPは不要）
  # なるべくノイズを減らすため dst host を指定（IPは自ホストのSIP公開IP想定）
  LOCAL_IP="$(hostname -I | awk '{print $1}')"
  echo "local_ip=${LOCAL_IP}"
  sudo timeout 360s tcpdump -i "${IFACE}" -s 0 -U -w "${PCAP_ANY}" "udp and dst host ${LOCAL_IP}" >/dev/null 2>&1 || true
  # latestを更新
  if [ -s "${PCAP_ANY}" ]; then
    cp -f "${PCAP_ANY}" "${PCAP_ANY_LATEST}"
  fi
  ls -l "${PCAP_ANY}" 2>/dev/null || true
  echo "capture_done"
}

analyze_latest() {
  echo "== analyze =="
  if [ ! -s "${PCAP_ANY_LATEST}" ]; then
    echo "ERR: pcap_any_latest_not_found ${PCAP_ANY_LATEST}"
    exit 2
  fi
  local uuid
  uuid="$(get_latest_uuid)"
  echo "uuid=${uuid}"
  if [ -z "${uuid}" ]; then
    echo "ERR: latest_uuid_not_found"
    exit 3
  fi
  local port
  port="$(get_local_media_port "${uuid}")"
  echo "local_media_port=${port}"
  if ! [[ "${port}" =~ ^[0-9]+$ ]]; then
    echo "ERR: local_media_port_invalid '${port}'"
    exit 4
  fi
  local out="/tmp/rtp_local_port_${port}_${TS}.pcap"
  echo "filtered_pcap=${out}"
  sudo timeout 30s tcpdump -r "${PCAP_ANY_LATEST}" -w "${out}" "udp and dst port ${port}" >/dev/null 2>&1 || true
  local cnt
  cnt="$(sudo timeout 10s tcpdump -r "${out}" 2>/dev/null | wc -l | tr -d ' ')"
  echo "packet_count=${cnt}"
  # 事実だけ: 0 or >0 の判定材料
  if [ "${cnt}" = "0" ]; then
    echo "RESULT: NO_RTP_TO_LOCAL_MEDIA_PORT"
  else
    echo "RESULT: RTP_REACHED_LOCAL_MEDIA_PORT"
  fi
  ls -l "${out}" 2>/dev/null || true
}

case "${MODE}" in
  capture) capture_any ;;
  analyze) analyze_latest ;;
  *)
    echo "Usage: $0 {capture|analyze}"
    exit 1
    ;;
esac
