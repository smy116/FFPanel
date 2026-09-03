from __future__ import annotations

import base64
import secrets
import uuid

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings


class BasicAuthMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"} or not self.settings.auth_enabled or scope.get("path") == "/healthz":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        authenticated = self._authenticated(headers.get("authorization"))
        if authenticated:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            status_code=401,
            content={"code": "unauthorized", "message": "需要身份认证", "details": None, "requestId": str(uuid.uuid4())},
            headers={"WWW-Authenticate": 'Basic realm="FFPanel", charset="UTF-8"'},
        )
        await response(scope, receive, send)

    def _authenticated(self, value: str | None) -> bool:
        if not value or not value.startswith("Basic "):
            return False
        try:
            username, password = base64.b64decode(value[6:], validate=True).decode("utf-8").split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return False
        return secrets.compare_digest(username, self.settings.auth_username or "") and secrets.compare_digest(password, self.settings.auth_password or "")
