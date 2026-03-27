"""Encrypted storage helpers for user-supplied execution sessions."""

from __future__ import annotations

import json
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import Settings


class SessionCipher:
    """Encrypt and decrypt execution session payloads."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._fernet = Fernet(self._require_key().encode("utf-8"))

    def encrypt_json(self, payload: Dict[str, Any]) -> str:
        """Encrypt a JSON-serializable payload."""

        encoded = json.dumps(payload).encode("utf-8")
        return self._fernet.encrypt(encoded).decode("utf-8")

    def decrypt_json(self, token: str) -> Dict[str, Any]:
        """Decrypt a stored encrypted payload."""

        try:
            raw = self._fernet.decrypt(token.encode("utf-8"))
        except InvalidToken as exc:
            raise RuntimeError("Stored execution session could not be decrypted.") from exc
        return json.loads(raw.decode("utf-8"))

    def _require_key(self) -> str:
        key = self._settings.session_encryption_key
        if not key:
            raise RuntimeError(
                "SESSION_ENCRYPTION_KEY is required for user-managed execution sessions."
            )
        return key
