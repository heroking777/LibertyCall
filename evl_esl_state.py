#!/usr/bin/env python3
"""EVL - グローバルESL接続状態管理"""

_esl_connection = None


def set_esl_connection(con):
    """PyESL接続をグローバルに設定"""
    global _esl_connection
    _esl_connection = con


def get_esl_connection():
    """PyESL接続を取得"""
    global _esl_connection
    return _esl_connection
