from __future__ import annotations

from starlette.datastructures import MutableHeaders


class SecurityHeadersMiddleware:
    """Attach browser security headers to all normal HTTP responses."""

    def __init__(
        self,
        app,
        *,
        is_development: bool,
    ):
        self.app = app
        self.is_development = is_development
        self._headers = self._build_headers()

    def _build_headers(self) -> dict[str, str]:
        script_sources = [
            "'self'",
            "https://cdn.jsdelivr.net",
        ]
        if self.is_development:
            # FastAPI's generated Swagger page contains an inline bootstrap
            # script. Production has no /docs route, so production CSP stays
            # strict for scripts.
            script_sources.append("'unsafe-inline'")

        csp = "; ".join([
            "default-src 'self'",
            "base-uri 'self'",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "img-src 'self' data:",
            (
                "style-src 'self' 'unsafe-inline' "
                "https://cdn.jsdelivr.net"
            ),
            f"script-src {' '.join(script_sources)}",
            "connect-src 'self'",
            "font-src 'self' data: https://cdn.jsdelivr.net",
        ])

        headers = {
            "Content-Security-Policy": csp,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": (
                "camera=(), microphone=(), geolocation=()"
            ),
            "Cross-Origin-Opener-Policy": "same-origin",
        }

        if not self.is_development:
            headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return headers

    async def __call__(
        self,
        scope,
        receive,
        send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)

                for key, value in self._headers.items():
                    if key not in headers:
                        headers[key] = value

                # Gateway responses can contain model output or security
                # assessment metadata and should never be cached.
                sensitive_paths = {
                    "/api/v1/chat",
                    "/v1/guard",
                    "/v1/chat/completions",
                }
                if (
                    scope.get("method") == "POST"
                    and scope.get("path") in sensitive_paths
                ):
                    headers["Cache-Control"] = "no-store"

            await send(message)

        await self.app(
            scope,
            receive,
            send_with_headers,
        )
