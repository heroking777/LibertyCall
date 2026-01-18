"""RTP sequence handling for ASR."""
from __future__ import annotations

from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.asr.asr_manager import GatewayASRManager


class ASRRTPBuffer:
    def __init__(self, manager: "GatewayASRManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    def should_process(
        self,
        sequence_number: Optional[int],
        effective_call_id: Optional[str],
        addr: Tuple[str, int],
    ) -> bool:
        if sequence_number is None:
            return True

        # effective_call_idが確定している場合はそれを使用、そうでない場合はaddrを使用
        check_key = effective_call_id if effective_call_id else str(addr)
        last_seq = self.manager._last_processed_sequence.get(check_key)
        if last_seq is not None and last_seq == sequence_number:
            # 既に処理済みなので、ログを出さずに静かにスキップ
            self.logger.debug(
                "[RTP_DUP] Skipping duplicate packet Seq=%s Key=%s",
                sequence_number,
                check_key,
            )
            return False

        # 未処理なら更新して続行
        self.manager._last_processed_sequence[check_key] = sequence_number
        # シーケンス番号をログ出力（100パケットごと）
        if sequence_number % 100 == 0:
            self.logger.warning(
                "[RTP_SEQ] Processing Seq=%s for %s",
                sequence_number,
                check_key,
            )
        return True
