# services/notice_push.py
"""공지사항 FCM 푸시 발송 서비스."""
from __future__ import annotations
import logging
from typing import List

from sqlalchemy.orm import Session

from database.session import SessionLocal
from core.firebase import init_firebase, is_initialized
from crud import notice as notice_crud
from crud import device_token as token_crud

log = logging.getLogger("notice_push")

# v0.2 — Android만 발송
TARGET_PLATFORMS = ["android"]


def _preview_text(md: str, max_len: int = 80) -> str:
    import re
    if not md:
        return ""
    s = re.sub(r"!\[[^\]]*\]\([^)]+\)", "[이미지]", md)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"[#*_`>~]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def push_notice(notice_id: int) -> dict:
    """주어진 공지를 활성 디바이스에 FCM으로 발송.

    별도 DB 세션을 새로 열어 사용 (스케줄러/엔드포인트 양쪽에서 안전 호출).
    반환: {"sent": N, "failed": M, "skipped": reason}
    """
    if not is_initialized():
        if not init_firebase():
            log.warning("Firebase 미초기화 — 푸시 스킵 (notice_id=%s)", notice_id)
            return {"sent": 0, "failed": 0, "skipped": "firebase_not_initialized"}

    # firebase_admin은 init 이후에만 import해야 안전
    from firebase_admin import messaging
    from firebase_admin.exceptions import FirebaseError

    db: Session = SessionLocal()
    try:
        notice = notice_crud.get(db, notice_id)
        if not notice:
            log.warning("공지 미존재 (notice_id=%s) — 푸시 스킵", notice_id)
            return {"sent": 0, "failed": 0, "skipped": "notice_not_found"}
        if not notice.is_important:
            log.info("일반 공지 (notice_id=%s) — 푸시 스킵", notice_id)
            return {"sent": 0, "failed": 0, "skipped": "not_important"}

        tokens = token_crud.list_active(db, platforms=TARGET_PLATFORMS)
        if not tokens:
            log.info("활성 디바이스 없음 — 푸시 스킵")
            return {"sent": 0, "failed": 0, "skipped": "no_active_devices"}

        title = f"[중요] {notice.title}"
        body = _preview_text(notice.content, 80)

        sent_total = 0
        failed_total = 0

        # FCM multicast는 한 번에 최대 500개
        chunk_size = 500
        for i in range(0, len(tokens), chunk_size):
            chunk = tokens[i : i + chunk_size]
            chunk_token_strs = [t.token for t in chunk]
            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                data={"type": "notice", "notice_id": str(notice.id)},
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        channel_id="notice_important",
                        sound="default",
                    ),
                ),
                tokens=chunk_token_strs,
            )

            try:
                response = messaging.send_each_for_multicast(message)
            except FirebaseError as e:
                log.exception("FCM 발송 실패 (chunk %d~%d): %s", i, i + len(chunk), e)
                failed_total += len(chunk)
                continue

            for idx, resp in enumerate(response.responses):
                if resp.success:
                    sent_total += 1
                else:
                    failed_total += 1
                    err = resp.exception
                    err_name = type(err).__name__ if err else "Unknown"
                    if err_name in ("UnregisteredError", "SenderIdMismatchError", "InvalidArgumentError"):
                        token_crud.deactivate(db, chunk[idx].token)
                        log.info("무효 토큰 비활성화: %s (사유: %s)", chunk[idx].token[:20], err_name)
                    else:
                        log.warning("토큰 발송 실패: %s (사유: %s)", chunk[idx].token[:20], err_name)

        log.info("푸시 완료 (notice_id=%s): sent=%d, failed=%d", notice_id, sent_total, failed_total)
        return {"sent": sent_total, "failed": failed_total}
    except Exception as e:
        log.exception("push_notice 예외: %s", e)
        return {"sent": 0, "failed": 0, "skipped": f"exception:{e}"}
    finally:
        db.close()
