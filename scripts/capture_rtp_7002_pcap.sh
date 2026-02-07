#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - FreeSWITCH→Gateway の UDP:7002 に「実際に」パケットが飛んでいるかを OSレベルで証拠化する。
#  - リアルタイム監視禁止のため、timeout+pcap保存で自動停止する。
#
# 使い方:
#  1) このスクリプトを実行して「READY」を出したらユーザーが10秒通話
#  2) 終了後に本スクリプトが自動停止し、オフラインでpcapを要約する

PCAP="/tmp/rtp_7002_$(date +%s).pcap"
SUM="/tmp/rtp_7002_last_summary.txt"

echo "[capture] writing pcap to: ${PCAP}"

# 重要: 無限待ち禁止。必ずtimeout。
# -i any: loopback含め全IFで拾う（127.0.0.1送信の可能性があるため）
# -c 400: 最大400パケットで停止（timeoutより先に止まる可能性あり）
if ! command -v tcpdump >/dev/null 2>&1; then
  echo "[error] tcpdump not found" >&2
  exit 1
fi

echo "READY: ユーザーは今から10秒通話してOK（この出力を見せてから通話してもらう）"

sudo timeout 18s tcpdump -i any -nn -s0 udp port 7002 -c 400 -w "${PCAP}" >/dev/null 2>&1 || true

echo "[capture] done. offline summary:"
{
  echo "== pcap file =="
  ls -lh "${PCAP}" || true
  echo
  echo "== packet count (read) =="
  # tcpdump -r は0でも成功することがあるので wc を採用
  sudo tcpdump -nn -r "${PCAP}" 2>/dev/null | wc -l || true
  echo
  echo "== first 3 packets (hex) =="
  sudo tcpdump -nn -xx -r "${PCAP}" -c 3 2>/dev/null || true
  echo
  echo "== last 3 packets (hex) =="
  # lastが無い環境を考慮してtail
  sudo tcpdump -nn -xx -r "${PCAP}" 2>/dev/null | tail -n 120 || true
} | tee "${SUM}" >/dev/null

echo "[ok] summary written: ${SUM}"
echo "[ok] pcap written: ${PCAP}"
