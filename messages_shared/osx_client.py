"""HTTP client for the speaker's jarvis-osx-api instance.

The binding is per-user command secrets (PRD decision #9): both secrets are
scope="user", so reads auto-key off the recognized speaker. Missing secrets
mean the speaker isn't bound to a Mac — callers hard-refuse.
"""

from __future__ import annotations

from typing import Any

import requests

from jarvis_command_sdk import JarvisStorage

INSTANCE_URL_SECRET = "user_osx_api_instance_url"
API_KEY_SECRET = "user_osx_api_api_key"

_DEFAULT_TIMEOUT = 10.0


class OsxApiError(Exception):
    """Transport failure or non-2xx from osx-api (send statuses excepted)."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class OsxApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = _DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            resp = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers,
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise OsxApiError(f"osx-api unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise OsxApiError(
                f"osx-api {path} returned {resp.status_code}", status_code=resp.status_code
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise OsxApiError(f"osx-api {path} returned non-JSON") from exc

    def unread(self) -> dict:
        return self._request("GET", "/v1/messages/unread")

    def thread(self, chat_id: str, limit: int = 30) -> dict:
        return self._request("GET", f"/v1/messages/threads/{chat_id}", params={"limit": limit})

    def style_context(self, chat_id: str) -> dict:
        return self._request("GET", f"/v1/messages/threads/{chat_id}/style-context")

    def mark_read(self, guids: list[str]) -> dict:
        return self._request("POST", "/v1/messages/mark-read", json={"guids": guids})

    def send(self, chat_id: str, text: str) -> dict:
        """Returns the service's status payload for BOTH success and send-level
        failures ({"status": "sent" | "unverified" | ...}); raises OsxApiError
        only for transport/auth-level problems."""
        try:
            resp = requests.post(
                f"{self.base_url}/v1/messages/send",
                headers=self._headers,
                json={"chat_id": chat_id, "text": text},
                timeout=max(self.timeout, 20.0),  # send verifies against chat.db; allow the poll
            )
        except requests.RequestException as exc:
            raise OsxApiError(f"osx-api unreachable: {exc}") from exc
        try:
            payload = resp.json()
        except ValueError as exc:
            raise OsxApiError(f"osx-api send returned non-JSON ({resp.status_code})") from exc
        if "status" not in payload:
            raise OsxApiError(f"osx-api send returned {resp.status_code}", resp.status_code)
        return payload


def client_from_storage(storage: JarvisStorage) -> OsxApiClient | None:
    """None = speaker has no binding secrets (hard refusal upstream).

    Single seam the tests monkeypatch."""
    url = storage.get_secret(INSTANCE_URL_SECRET, scope="user")
    key = storage.get_secret(API_KEY_SECRET, scope="user")
    if not url or not key:
        return None
    return OsxApiClient(url, key)
