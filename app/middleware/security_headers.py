"""Baseline security response headers.

The header set mirrors the hardening applied by the sibling backend so that both
deployments present the same posture to a browser.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Applied to every response.
BASE_HEADERS: tuple[tuple[str, str], ...] = (
    ("cross-origin-opener-policy", "same-origin"),
    ("cross-origin-resource-policy", "same-origin"),
    ("origin-agent-cluster", "?1"),
    ("referrer-policy", "no-referrer"),
    ("strict-transport-security", "max-age=31536000; includeSubDomains"),
    ("x-content-type-options", "nosniff"),
    ("x-dns-prefetch-control", "off"),
    ("x-download-options", "noopen"),
    ("x-frame-options", "SAMEORIGIN"),
    ("x-permitted-cross-domain-policies", "none"),
    # Explicitly disabled: the legacy XSS auditor introduces vulnerabilities of
    # its own, and modern browsers ignore anything but `0`.
    ("x-xss-protection", "0"),
)

# Directive order and separator are byte-for-byte the baseline policy, so the
# header can be diffed against the sibling deployment without normalising it.
# `script-src-attr 'none'` is load-bearing: without it an inline `onclick=` is
# still allowed even though `script-src 'self'` blocks inline `<script>`.
CONTENT_SECURITY_POLICY = (
    "default-src 'self';base-uri 'self';font-src 'self' https: data:;"
    "form-action 'self';frame-ancestors 'self';img-src 'self' data:;"
    "object-src 'none';script-src 'self';script-src-attr 'none';"
    "style-src 'self' https: 'unsafe-inline';upgrade-insecure-requests"
)


class SecurityHeadersMiddleware:
    """Adds the hardening headers, leaving any the application already set."""

    def __init__(self, app: ASGIApp, *, csp_exempt_paths: frozenset[str] = frozenset()) -> None:
        self.app = app
        # The interactive documentation pulls its bundle from a CDN, so the
        # policy above would blank the page. Those two routes are exempted
        # rather than the policy being weakened for the whole application.
        self.csp_exempt_paths = csp_exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        send_csp = path not in self.csp_exempt_paths

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}

                for name, value in BASE_HEADERS:
                    if name.encode("latin-1") not in present:
                        headers.append((name.encode("latin-1"), value.encode("latin-1")))

                if send_csp and b"content-security-policy" not in present:
                    headers.append(
                        (
                            b"content-security-policy",
                            CONTENT_SECURITY_POLICY.encode("latin-1"),
                        )
                    )

                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
