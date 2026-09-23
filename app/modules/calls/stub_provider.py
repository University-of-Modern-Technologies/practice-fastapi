"""In-repo stand-in for the telephony provider.

The default configuration has no provider address, and without this the whole
module would be dead on a fresh checkout: nothing to sync, nothing to link,
nothing to listen back. The stub keeps the system runnable end to end with no
account, no key and no network.

The journal is generated from a fixed anchor rather than from the clock, so the
same run always produces the same records — which is what makes the second
``POST /calls/sync`` skip every one of them instead of merely being likely to,
and what makes this usable as a fixture as well as a placeholder.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from app.db.enums import CallDirection, CallDisposition
from app.modules.calls.provider import CallProviderFetchRequest, ProviderCall

__all__ = [
    "STUB_CALL_JOURNAL_SIZE",
    "STUB_CALL_PROVIDER_NAME",
    "StubCallProvider",
    "create_stub_call_provider",
    "stub_journal",
]

STUB_CALL_PROVIDER_NAME = "stub"

#: The whole universe the stub knows about; ``limit`` slices into it.
STUB_CALL_JOURNAL_SIZE = 25

#: Newest call in the generated journal. Fixed, so runs are reproducible.
_ANCHOR = datetime(2026, 1, 2, 9, 0, 0, tzinfo=UTC)

#: Spacing between consecutive generated calls, counting backwards.
_STEP = timedelta(minutes=17)

_DISPOSITIONS: tuple[CallDisposition, ...] = (
    CallDisposition.ANSWERED,
    CallDisposition.NO_ANSWER,
    CallDisposition.ANSWERED,
    CallDisposition.BUSY,
    CallDisposition.ANSWERED,
    CallDisposition.VOICEMAIL,
    CallDisposition.FAILED,
)

_OFFICE_NUMBER = "+14155550100"

_BASE_DURATION_SECONDS = 45
_DURATION_STEP_SECONDS = 13


def _caller_number(index: int) -> str:
    """A caller per record, drawn from a documentation range.

    Nothing in the fixture can therefore ever dial a real person.
    """
    return f"+1415555{1000 + index}"


def _record_for(index: int) -> ProviderCall:
    disposition = _DISPOSITIONS[index % len(_DISPOSITIONS)]
    inbound = index % 2 == 0
    # Only a conversation has a duration and a recording; the rest are zero, so
    # the "no recording" branch is reachable from the stub alone.
    answered = disposition is CallDisposition.ANSWERED
    external_id = f"stub-call-{index + 1:04d}"
    caller = _caller_number(index)

    return ProviderCall(
        external_id=external_id,
        direction=CallDirection.INBOUND if inbound else CallDirection.OUTBOUND,
        disposition=disposition,
        from_number=caller if inbound else _OFFICE_NUMBER,
        to_number=_OFFICE_NUMBER if inbound else caller,
        started_at=_ANCHOR - _STEP * index,
        duration_seconds=(
            _BASE_DURATION_SECONDS + index * _DURATION_STEP_SECONDS if answered else 0
        ),
        recording_url=f"https://recordings.invalid/{external_id}.mp3" if answered else None,
    )


def stub_journal() -> tuple[ProviderCall, ...]:
    """The whole journal the stub knows, built from the index alone."""
    return tuple(_record_for(index) for index in range(STUB_CALL_JOURNAL_SIZE))


class StubCallProvider:
    """Answers the telephony protocol from memory, without a network call."""

    name = STUB_CALL_PROVIDER_NAME

    def __init__(self) -> None:
        self._journal = stub_journal()

    async def fetch_calls(self, request: CallProviderFetchRequest) -> Sequence[ProviderCall]:
        return self._journal[: max(0, request.limit)]


def create_stub_call_provider() -> StubCallProvider:
    """Builds the offline provider."""
    return StubCallProvider()
