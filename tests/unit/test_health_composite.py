from __future__ import annotations

import asyncio

from app.health.composite import create_composite_readiness_check
from app.health.readiness import ReadinessCheck, run_readiness_checks


async def _never() -> None:
    await asyncio.sleep(10)


async def test_satisfies_the_same_interface_as_a_plain_check() -> None:
    composite = create_composite_readiness_check(
        "database",
        [
            ReadinessCheck(name="connection", check=_ok),
            ReadinessCheck(name="schema", check=_ok),
        ],
    )

    (result,) = await run_readiness_checks([composite])

    assert result.name == "database"
    assert result.status == "up"
    assert result.critical is True


async def _ok() -> None:
    return None


async def _boom() -> None:
    message = "migration pending"
    raise RuntimeError(message)


async def test_fails_when_a_critical_sub_check_fails() -> None:
    composite = create_composite_readiness_check(
        "database",
        [
            ReadinessCheck(name="connection", check=_ok),
            ReadinessCheck(name="schema", check=_boom),
        ],
    )

    (result,) = await run_readiness_checks([composite])

    assert result.status == "down"
    assert result.critical is True
    # The cause is available for the log line, but never meant for the response.
    assert "schema" in repr(result.error)


def test_is_non_critical_only_when_every_sub_check_is_non_critical() -> None:
    all_non_critical = create_composite_readiness_check(
        "optional-group",
        [
            ReadinessCheck(name="a", check=_ok, critical=False),
            ReadinessCheck(name="b", check=_ok, critical=False),
        ],
    )
    mixed = create_composite_readiness_check(
        "mixed-group",
        [
            ReadinessCheck(name="a", check=_ok, critical=False),
            ReadinessCheck(name="b", check=_ok),
        ],
    )

    assert all_non_critical.critical is False
    assert mixed.critical is True


async def test_does_not_fail_when_only_a_non_critical_sub_check_fails() -> None:
    composite = create_composite_readiness_check(
        "database",
        [
            ReadinessCheck(name="connection", check=_ok),
            ReadinessCheck(name="search-hint", check=_boom, critical=False),
        ],
    )

    (result,) = await run_readiness_checks([composite])

    assert result.status == "up"


async def test_a_hung_sub_check_times_out_on_its_own_without_blocking_a_sibling() -> None:
    composite = create_composite_readiness_check(
        "database",
        [
            ReadinessCheck(name="connection", check=_ok),
            ReadinessCheck(name="schema", check=_never),
        ],
        sub_check_timeout_seconds=0.02,
    )

    (result,) = await run_readiness_checks([composite], default_timeout_seconds=5)

    assert result.status == "down"


async def test_a_hung_composite_does_not_block_a_sibling_top_level_check() -> None:
    stuck = create_composite_readiness_check(
        "database",
        [ReadinessCheck(name="connection", check=_never)],
        sub_check_timeout_seconds=10,
        timeout_seconds=0.03,
    )

    results = await run_readiness_checks(
        [stuck, ReadinessCheck(name="cache", check=_ok)], default_timeout_seconds=5
    )

    by_name = {result.name: result for result in results}
    assert by_name["database"].status == "timed_out"
    assert by_name["cache"].status == "up"
