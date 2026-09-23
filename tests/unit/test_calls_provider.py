"""The telephony adapter: the stub, the retry policy and the HTTP boundary.

Nothing here opens a socket. The transport is a seam, so what is exercised is
the part that decides *how* a failure is treated — which is the part that would
otherwise only be observable against a provider having a bad day.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import pytest

from app.core.errors import AppError
from app.db.enums import CallDirection, CallDisposition
from app.modules.calls.http_provider import (
    CALLS_BATCH_PATH,
    CallTransportRequest,
    CallTransportResponse,
    HttpCallProvider,
    HttpCallProviderOptions,
)
from app.modules.calls.provider import (
    MAX_PROVIDER_BATCH_SIZE,
    CallProviderFetchRequest,
    ProviderCall,
    RetryableProviderError,
    RetryingCallProvider,
    RetryOptions,
    call_provider_unavailable_error,
)
from app.modules.calls.provider_factory import (
    DEFAULT_CALL_SYNC_BATCH_SIZE,
    CallProviderConfig,
    create_call_provider,
)
from app.modules.calls.stub_provider import (
    STUB_CALL_JOURNAL_SIZE,
    StubCallProvider,
    stub_journal,
)
from app.modules.calls.types import CALL_PROVIDER_UNAVAILABLE

E164 = re.compile(r"^\+[1-9]\d{1,14}$")

#: The provider speaks camelCase on the wire, as the sibling backend reads it.
VALID_CALL: dict[str, Any] = {
    "externalId": "pbx-991",
    "direction": "INBOUND",
    "disposition": "ANSWERED",
    "fromNumber": "+14155551000",
    "toNumber": "+14155550100",
    "startedAt": "2026-09-01T08:00:00.000Z",
    "durationSeconds": 61,
    "recordingUrl": "https://recordings.invalid/pbx-991.mp3",
}

FETCH = CallProviderFetchRequest(limit=DEFAULT_CALL_SYNC_BATCH_SIZE)


async def no_delay(milliseconds: float) -> None:
    pass


class ScriptedProvider:
    """Stands in for a real provider; each attempt pops the next answer."""

    name = "inner"

    def __init__(self, script: list[Sequence[ProviderCall] | Exception]) -> None:
        self._script = script
        self.attempts = 0
        self.requests: list[CallProviderFetchRequest] = []

    async def fetch_calls(self, request: CallProviderFetchRequest) -> Sequence[ProviderCall]:
        self.requests.append(request)
        entry = self._script[min(self.attempts, len(self._script) - 1)]
        self.attempts += 1
        if isinstance(entry, Exception):
            raise entry
        return entry


class ScriptedTransport:
    """A network seam that answers from a list instead of from a socket."""

    def __init__(self, script: list[CallTransportResponse | Exception]) -> None:
        self._script = script
        self.requests: list[CallTransportRequest] = []

    async def send(self, request: CallTransportRequest) -> CallTransportResponse:
        self.requests.append(request)
        entry = self._script[min(len(self.requests) - 1, len(self._script) - 1)]
        if isinstance(entry, Exception):
            raise entry
        return entry


def make_http_provider(
    script: list[CallTransportResponse | Exception],
) -> tuple[HttpCallProvider, ScriptedTransport]:
    transport = ScriptedTransport(script)
    provider = HttpCallProvider(
        HttpCallProviderOptions(base_url="https://pbx.invalid", transport=transport)
    )
    return provider, transport


# --- the stub -------------------------------------------------------------


async def test_the_stub_answers_without_any_configuration() -> None:
    batch = await StubCallProvider().fetch_calls(FETCH)

    assert len(batch) == STUB_CALL_JOURNAL_SIZE


async def test_the_stub_reports_the_same_batch_every_time() -> None:
    # This is what makes the second sync assertable rather than merely likely:
    # the batch depends on neither the clock nor how often it was asked for.
    first = await StubCallProvider().fetch_calls(FETCH)
    second = await StubCallProvider().fetch_calls(FETCH)
    third = await StubCallProvider().fetch_calls(FETCH)

    assert list(first) == list(second) == list(third)


def test_the_stub_hands_out_distinct_identifiers() -> None:
    # A batch that repeated an id would make the whole idempotency story
    # untestable: every second mention would be "already on file" by accident.
    identifiers = {item.external_id for item in stub_journal()}

    assert len(identifiers) == STUB_CALL_JOURNAL_SIZE


def test_every_stub_number_is_e164() -> None:
    # The stub speaks the format the real provider is documented to speak, so
    # the code under test is the code that runs in production.
    for item in stub_journal():
        assert E164.fullmatch(item.from_number)
        assert E164.fullmatch(item.to_number)


def test_only_a_conversation_has_a_duration_and_a_recording() -> None:
    # Which is what makes the recording endpoint's 404 reachable from the stub
    # alone: a call that was never picked up has nothing to listen to.
    journal = stub_journal()
    unanswered = [item for item in journal if item.disposition is not CallDisposition.ANSWERED]

    assert unanswered
    for item in unanswered:
        assert item.duration_seconds == 0
        assert item.recording_url is None
    for item in journal:
        if item.disposition is CallDisposition.ANSWERED:
            assert item.duration_seconds > 0
            assert item.recording_url is not None


def test_the_journal_is_anchored_where_both_backends_anchor_it() -> None:
    """The stub is shared fixture data, so its first record is pinned.

    A sync fills the call log from here, and the log is then compared across
    the two backends — so the anchor, the spacing and the identifiers are part
    of the observable contract rather than an implementation detail.
    """
    first = stub_journal()[0]

    assert first.external_id == "stub-call-0001"
    assert first.started_at.isoformat() == "2026-01-02T09:00:00+00:00"
    assert first.direction is CallDirection.INBOUND
    assert first.from_number == "+14155551000"
    assert first.to_number == "+14155550100"
    assert stub_journal()[-1].external_id == "stub-call-0025"


def test_the_journal_runs_backwards_from_the_anchor() -> None:
    journal = stub_journal()

    assert all(
        journal[index].started_at > journal[index + 1].started_at
        for index in range(len(journal) - 1)
    )


async def test_the_limit_slices_into_the_journal() -> None:
    # How large a batch may be is a deployment setting, and the provider obeys
    # it rather than handing over everything it knows.
    batch = await StubCallProvider().fetch_calls(CallProviderFetchRequest(limit=3))

    assert [item.external_id for item in batch] == [
        "stub-call-0001",
        "stub-call-0002",
        "stub-call-0003",
    ]


def test_the_stub_reports_traffic_in_both_directions() -> None:
    directions = {item.direction for item in stub_journal()}

    assert directions == {CallDirection.INBOUND, CallDirection.OUTBOUND}


# --- the retry policy -----------------------------------------------------


async def test_a_transient_failure_is_repeated_until_it_succeeds() -> None:
    inner = ScriptedProvider(
        [RetryableProviderError(call_provider_unavailable_error()), [], []],
    )
    provider = RetryingCallProvider(inner, RetryOptions(max_attempts=3, delay=no_delay))

    assert await provider.fetch_calls(FETCH) == []
    assert inner.attempts == 2


async def test_attempts_are_bounded_and_the_failure_is_reported_as_agreed() -> None:
    inner = ScriptedProvider([RetryableProviderError(call_provider_unavailable_error())])
    provider = RetryingCallProvider(inner, RetryOptions(max_attempts=3, delay=no_delay))

    with pytest.raises(AppError) as error:
        await provider.fetch_calls(FETCH)

    assert inner.attempts == 3
    assert error.value.status_code == 502
    assert error.value.code == CALL_PROVIDER_UNAVAILABLE


async def test_a_failure_that_is_not_transient_is_not_repeated() -> None:
    # Repeating a request the provider understood and refused changes nothing.
    inner = ScriptedProvider([call_provider_unavailable_error()])
    provider = RetryingCallProvider(inner, RetryOptions(max_attempts=3, delay=no_delay))

    with pytest.raises(AppError):
        await provider.fetch_calls(FETCH)

    assert inner.attempts == 1


async def test_the_pause_between_attempts_grows() -> None:
    waited: list[float] = []

    async def record(milliseconds: float) -> None:
        waited.append(milliseconds)

    inner = ScriptedProvider([RetryableProviderError(call_provider_unavailable_error())])
    provider = RetryingCallProvider(
        inner, RetryOptions(max_attempts=3, backoff_ms=100, delay=record)
    )

    with pytest.raises(AppError):
        await provider.fetch_calls(FETCH)

    # A provider that is merely busy must not be hammered while it recovers.
    assert waited == [100, 200]


# --- the HTTP boundary ----------------------------------------------------


async def test_a_well_formed_batch_is_mapped_onto_the_domain_shape() -> None:
    provider, transport = make_http_provider([CallTransportResponse(status=200, body=[VALID_CALL])])

    batch = await provider.fetch_calls(FETCH)

    assert transport.requests[0].path == CALLS_BATCH_PATH
    assert len(batch) == 1
    assert batch[0].external_id == "pbx-991"
    assert batch[0].direction is CallDirection.INBOUND
    assert batch[0].disposition is CallDisposition.ANSWERED


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_transient_status_is_offered_for_retry(status: int) -> None:
    provider, _ = make_http_provider([CallTransportResponse(status=status, body=None)])

    with pytest.raises(RetryableProviderError):
        await provider.fetch_calls(FETCH)


async def test_a_network_failure_is_offered_for_retry() -> None:
    provider, _ = make_http_provider([OSError("connection refused")])

    with pytest.raises(RetryableProviderError):
        await provider.fetch_calls(FETCH)


@pytest.mark.parametrize("status", [400, 401, 404])
async def test_a_refusal_is_reported_rather_than_retried(status: int) -> None:
    provider, _ = make_http_provider([CallTransportResponse(status=status, body=None)])

    with pytest.raises(AppError) as error:
        await provider.fetch_calls(FETCH)

    assert not isinstance(error.value, RetryableProviderError)
    assert error.value.code == CALL_PROVIDER_UNAVAILABLE


@pytest.mark.parametrize(
    "body",
    [
        None,
        [VALID_CALL | {"fromNumber": "0671230001"}],
        [VALID_CALL | {"startedAt": "2026-09-01T08:00:00"}],
        [VALID_CALL | {"durationSeconds": -1}],
        [VALID_CALL | {"disposition": "PICKED_UP"}],
        [VALID_CALL | {"externalId": ""}],
    ],
)
async def test_a_payload_outside_the_contract_never_becomes_a_row(body: Any) -> None:
    # The one thing worse than a failed sync is a successful one that fills the
    # call log with values no schema ever checked.
    provider, _ = make_http_provider([CallTransportResponse(status=200, body=body)])

    with pytest.raises(AppError) as error:
        await provider.fetch_calls(FETCH)

    assert error.value.code == CALL_PROVIDER_UNAVAILABLE


async def test_an_unbounded_batch_is_refused() -> None:
    oversized = [
        VALID_CALL | {"externalId": f"pbx-{index}"} for index in range(MAX_PROVIDER_BATCH_SIZE + 1)
    ]
    provider, _ = make_http_provider([CallTransportResponse(status=200, body=oversized)])

    with pytest.raises(AppError):
        await provider.fetch_calls(FETCH)


async def test_the_reported_failure_names_no_upstream_detail() -> None:
    # The base URL, the key and the provider's own error text stay in the log,
    # on our side of the boundary.
    provider, _ = make_http_provider([CallTransportResponse(status=500, body={"why": "meltdown"})])

    with pytest.raises(RetryableProviderError) as error:
        await provider.fetch_calls(FETCH)

    assert "pbx.invalid" not in error.value.failure.message
    assert "meltdown" not in error.value.failure.message


# --- choosing one --------------------------------------------------------


async def test_no_configured_address_means_the_offline_stub() -> None:
    provider = create_call_provider(CallProviderConfig())

    assert len(await provider.fetch_calls(FETCH)) == STUB_CALL_JOURNAL_SIZE


async def test_a_configured_address_means_the_endpoint_and_the_same_retry_layer() -> None:
    transport = ScriptedTransport([CallTransportResponse(status=503, body=None)])
    provider = create_call_provider(
        CallProviderConfig(base_url="https://pbx.invalid", max_attempts=2, backoff_ms=0),
        transport=transport,
    )

    with pytest.raises(AppError) as error:
        await provider.fetch_calls(FETCH)

    assert len(transport.requests) == 2
    assert error.value.code == CALL_PROVIDER_UNAVAILABLE
