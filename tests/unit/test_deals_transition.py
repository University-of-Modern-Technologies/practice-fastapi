"""The deal stage machine, exercised as the pure functions it is made of."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.errors import AppError, ConflictError
from app.db.enums import DealStage
from app.modules.deals.transition import (
    ALLOWED_DEAL_STAGE_TRANSITIONS,
    DEFAULT_DEAL_PROBABILITY,
    TERMINAL_DEAL_STAGES,
    assert_deal_probability,
    assert_deal_stage_transition,
    can_transition_deal_stage,
    closed_at_for_stage,
    is_terminal_deal_stage,
    resolve_transition_probability,
)
from app.modules.deals.types import INVALID_DEAL_PROBABILITY, INVALID_DEAL_STAGE_TRANSITION

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)


def test_the_transition_graph_is_exactly_the_canonical_one() -> None:
    assert ALLOWED_DEAL_STAGE_TRANSITIONS == {
        DealStage.LEAD: (DealStage.QUALIFIED,),
        DealStage.QUALIFIED: (DealStage.PROPOSAL,),
        DealStage.PROPOSAL: (DealStage.WON, DealStage.LOST),
        DealStage.WON: (),
        DealStage.LOST: (),
    }


def test_every_pair_of_stages_agrees_with_the_graph() -> None:
    for source in DealStage:
        for target in DealStage:
            allowed = target in ALLOWED_DEAL_STAGE_TRANSITIONS[source]
            assert can_transition_deal_stage(source, target) is allowed


@pytest.mark.parametrize("stage", TERMINAL_DEAL_STAGES)
def test_a_closed_deal_never_reopens(stage: DealStage) -> None:
    assert ALLOWED_DEAL_STAGE_TRANSITIONS[stage] == ()
    assert is_terminal_deal_stage(stage) is True

    for target in DealStage:
        assert can_transition_deal_stage(stage, target) is False
        with pytest.raises(ConflictError):
            assert_deal_stage_transition(stage, target)


def test_an_illegal_move_is_a_conflict_that_names_the_way_out() -> None:
    with pytest.raises(ConflictError) as error:
        assert_deal_stage_transition(DealStage.LEAD, DealStage.WON)

    assert error.value.status_code == 409
    assert error.value.code == INVALID_DEAL_STAGE_TRANSITION
    assert error.value.details == {"from": "LEAD", "to": "WON", "allowed": ["QUALIFIED"]}


def test_a_legal_move_passes_silently() -> None:
    assert_deal_stage_transition(DealStage.PROPOSAL, DealStage.WON)
    assert_deal_stage_transition(DealStage.LEAD, DealStage.QUALIFIED)


@pytest.mark.parametrize(
    ("stage", "probability"),
    [
        (DealStage.LEAD, 10),
        (DealStage.QUALIFIED, 25),
        (DealStage.PROPOSAL, 99),
        (DealStage.WON, 100),
        (DealStage.LOST, 0),
    ],
)
def test_a_probability_that_matches_its_stage_is_accepted(
    stage: DealStage, probability: int
) -> None:
    assert_deal_probability(stage, probability)


@pytest.mark.parametrize(
    ("stage", "probability"),
    [
        (DealStage.LEAD, 100),
        (DealStage.QUALIFIED, 100),
        (DealStage.WON, 90),
        (DealStage.LOST, 10),
        (DealStage.QUALIFIED, -1),
        (DealStage.QUALIFIED, 101),
    ],
)
def test_a_probability_that_contradicts_its_stage_is_rejected(
    stage: DealStage, probability: int
) -> None:
    with pytest.raises(AppError) as error:
        assert_deal_probability(stage, probability)

    assert error.value.status_code == 400
    assert error.value.code == INVALID_DEAL_PROBABILITY


def test_the_default_probability_of_a_stage_satisfies_its_own_rule() -> None:
    for stage, probability in DEFAULT_DEAL_PROBABILITY.items():
        assert_deal_probability(stage, probability)


@pytest.mark.parametrize(
    ("stage", "expected"),
    [(DealStage.WON, 100), (DealStage.LOST, 0), (DealStage.QUALIFIED, 42)],
)
def test_a_closing_deal_takes_the_certainty_its_outcome_implies(
    stage: DealStage, expected: int
) -> None:
    assert resolve_transition_probability(stage, None, 42) == expected


def test_an_explicit_probability_wins_over_the_stage_default() -> None:
    assert resolve_transition_probability(DealStage.WON, 100, 42) == 100


def test_only_a_terminal_stage_stamps_a_closing_moment() -> None:
    assert closed_at_for_stage(DealStage.WON, NOW) == NOW
    assert closed_at_for_stage(DealStage.LOST, NOW) == NOW
    assert closed_at_for_stage(DealStage.QUALIFIED, NOW) is None


def test_a_closing_moment_defaults_to_the_present() -> None:
    stamped = closed_at_for_stage(DealStage.WON)

    assert stamped is not None
    assert stamped.tzinfo is not None
