# core/firebase.py
"""Firebase Admin SDK 초기화 (FCM 발송용)."""
from __future__ import annotations
import os
import logging
from typing import Optional

import firebase_admin
from firebase_admin import credentials

log = logging.getLogger("firebase")

_INITIALIZED = False
_INIT_ERROR: Optional[Exception] = None


def init_firebase() -> bool:
    """Firebase Admin SDK 초기화. 성공 시 True, 실패 시 False (에러 로그)."""
    global _INITIALIZED, _INIT_ERROR
    if _INITIALIZED:
        return True

    sa_path = os.getenv("FIREBASE_SA_PATH")
    if not sa_path:
        _INIT_ERROR = RuntimeError("FIREBASE_SA_PATH not set")
        log.warning("FIREBASE_SA_PATH 환경변수 미설정 — 푸시 발송 비활성화")
        return False
    if not os.path.exists(sa_path):
        _INIT_ERROR = FileNotFoundError(sa_path)
        log.warning("Firebase 서비스 계정 키 파일 없음: %s — 푸시 발송 비활성화", sa_path)
        return False

    try:
        cred = credentials.Certificate(sa_path)
        firebase_admin.initialize_app(cred)
        _INITIALIZED = True
        log.info("Firebase Admin SDK 초기화 완료")
        return True
    except Exception as e:
        _INIT_ERROR = e
        log.exception("Firebase 초기화 실패: %s", e)
        return False


def is_initialized() -> bool:
    return _INITIALIZED
