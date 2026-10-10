"""Credentials never reach a log line in clear text.

The refresh flow hands the client a fresh token in ``Set-Cookie``; a response
header is as much a credential carrier as the request's ``Cookie`` and
``Authorization`` are, so all three are pinned here.
"""

from __future__ import annotations

from app.core.logging import REDACTED, redact_processor

REFRESH_TOKEN = "refresh-token-value-that-must-not-leak"


def test_request_and_response_credentials_are_redacted() -> None:
    line = redact_processor(
        None,
        "info",
        {
            "event": "request completed",
            "request": {
                "headers": {
                    "authorization": "Bearer access-token",
                    "cookie": f"refreshToken={REFRESH_TOKEN}",
                }
            },
            "response": {"headers": {"set-cookie": f"refreshToken={REFRESH_TOKEN}; HttpOnly"}},
        },
    )

    assert REFRESH_TOKEN not in repr(line)
    assert line["request"]["headers"]["authorization"] == REDACTED
    assert line["request"]["headers"]["cookie"] == REDACTED
    assert line["response"]["headers"]["set-cookie"] == REDACTED


def test_a_top_level_set_cookie_field_is_redacted() -> None:
    line = redact_processor(None, "info", {"event": "x", "Set-Cookie": REFRESH_TOKEN})

    assert line["Set-Cookie"] == REDACTED
