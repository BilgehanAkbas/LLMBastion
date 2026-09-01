from __future__ import annotations

from starlette.responses import JSONResponse

from ..core.errors import build_error_body


class RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Limit the raw body size of POST /api/v1/chat.

    The limit is enforced from Content-Length when available and again while
    consuming ASGI body chunks, so chunked/no-length requests are also bounded.
    """

    def __init__(
        self,
        app,
        *,
        max_bytes: int,
    ):
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")

        self.app = app
        self.max_bytes = max_bytes

    async def __call__(
        self,
        scope,
        receive,
        send,
    ) -> None:
        if not (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/api/v1/chat"
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_content_length = headers.get(b"content-length")

        if raw_content_length is not None:
            try:
                content_length = int(
                    raw_content_length.decode("ascii")
                )
            except (UnicodeDecodeError, ValueError):
                content_length = None

            if (
                content_length is not None
                and content_length > self.max_bytes
            ):
                await self._reject(scope, receive, send)
                return

        received_bytes = 0

        async def limited_receive():
            nonlocal received_bytes

            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(
                    message.get("body", b"")
                )
                if received_bytes > self.max_bytes:
                    raise RequestBodyTooLarge

            return message

        try:
            await self.app(
                scope,
                limited_receive,
                send,
            )
        except RequestBodyTooLarge:
            await self._reject(scope, receive, send)

    async def _reject(
        self,
        scope,
        receive,
        send,
    ) -> None:
        response = JSONResponse(
            status_code=413,
            content=build_error_body(
                "request_too_large",
                "Request body is too large",
                details={
                    "max_bytes": self.max_bytes,
                },
            ),
        )
        await response(scope, receive, send)
