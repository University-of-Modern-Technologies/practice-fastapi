"""The deal stage machine.

Every rule about *which* stage may follow *which* lives here, as plain
functions over plain values: no session, no request, nothing to mock. That is
deliberate — the pipeline is the part of this module a mistake would be most
expensive in, so it has to be testable without a database.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from app.core.errors import AppError, ConflictError
from app.db.enums import DealStage
from app.modules.deals.state import deal_state
from app.modules.deals.types import (
    INVALID_DEAL_PROBABILITY,
    INVALID_DEAL_STAGE_TRANSITION,
)

__all__ = [
    "ALLOWED_DEAL_STAGE_TRANSITIONS",
    "DEFAULT_DEAL_PROBABILITY",
    "LOST_PROBABILITY",
    "MAX_PROBABILITY",
    "MIN_PROBABILITY",
    "TERMINAL_DEAL_STAGES",
    "WON_PROBABILITY",
    "assert_deal_probability",
    "assert_deal_stage_transition",
    "can_transition_deal_stage",
    "closed_at_for_stage",
    "is_terminal_deal_stage",
    "resolve_transition_probability",
]

#: The pipeline, derived from the states rather than written out again, so
#: this table and the one baked into each state can never drift apart. A stage
#: that is absent from a target list is unreachable from that source —
#: including backwards, which is why a mistake cannot be undone by moving a
#: deal back but only by opening a new one.
ALLOWED_DEAL_STAGE_TRANSITIONS: Mapping[DealStage, tuple[DealStage, ...]] = {
    stage: deal_state(stage).allowed_transitions for stage in DealStage
}

#: Stages a deal never leaves; both have an empty target list above.
TERMINAL_DEAL_STAGES = (DealStage.WON, DealStage.LOST)

MIN_PROBABILITY = 0
MAX_PROBABILITY = 100

#: A closed deal has a known outcome, so its probability is not an estimate.
WON_PROBABILITY = MAX_PROBABILITY
LOST_PROBABILITY = MIN_PROBABILITY

#: What a deal is worth betting on when the caller states no figure.
DEFAULT_DEAL_PROBABILITY: Mapping[DealStage, int] = {
    DealStage.LEAD: 10,
    DealStage.QUALIFIED: 25,
    DealStage.PROPOSAL: 50,
    DealStage.WON: WON_PROBABILITY,
    DealStage.LOST: LOST_PROBABILITY,
}


def is_terminal_deal_stage(stage: DealStage) -> bool:
    """Whether the pipeline ends at this stage."""
    return stage in TERMINAL_DEAL_STAGES


def can_transition_deal_stage(from_stage: DealStage, to_stage: DealStage) -> bool:
    """Whether the machine permits this move."""
    return to_stage in deal_state(from_stage).allowed_transitions


def assert_deal_stage_transition(from_stage: DealStage, to_stage: DealStage) -> None:
    """Rejects a move the pipeline does not allow.

    Reported as a conflict rather than a validation failure: the requested
    stage is a perfectly valid value, it just contradicts the state the deal is
    in — which is something the client can only learn by re-reading the record.
    """
    if can_transition_deal_stage(from_stage, to_stage):
        return
    raise ConflictError(
        f"Deal stage cannot transition from {from_stage} to {to_stage}",
        INVALID_DEAL_STAGE_TRANSITION,
        {
            "from": str(from_stage),
            "to": str(to_stage),
            "allowed": [str(stage) for stage in deal_state(from_stage).allowed_transitions],
        },
    )


def assert_deal_probability(stage: DealStage, probability: int) -> None:
    """Rejects a probability that contradicts the stage it is written with.

    The same rule is enforced by a check constraint in the database; it is
    repeated here so that the client gets a named error instead of a driver
    exception, and so the rule can be read in one place.
    """
    if probability < MIN_PROBABILITY or probability > MAX_PROBABILITY:
        raise AppError(
            f"Probability must be an integer from {MIN_PROBABILITY} to {MAX_PROBABILITY}",
            400,
            INVALID_DEAL_PROBABILITY,
        )
    if deal_state(stage).is_valid_probability(probability):
        return
    if stage is DealStage.WON:
        raise AppError(
            f"Won deals must have {WON_PROBABILITY} probability", 400, INVALID_DEAL_PROBABILITY
        )
    if stage is DealStage.LOST:
        raise AppError(
            f"Lost deals must have {LOST_PROBABILITY} probability", 400, INVALID_DEAL_PROBABILITY
        )
    raise AppError(
        f"Only won deals may have {MAX_PROBABILITY} probability",
        400,
        INVALID_DEAL_PROBABILITY,
    )


def resolve_transition_probability(stage: DealStage, requested: int | None, current: int) -> int:
    """The probability a deal carries after moving to ``stage``.

    An explicit figure wins; otherwise a closing deal takes the certainty its
    outcome implies and an open one keeps the estimate it already had.
    """
    if requested is not None:
        return requested
    if stage is DealStage.WON:
        return WON_PROBABILITY
    if stage is DealStage.LOST:
        return LOST_PROBABILITY
    return current


def closed_at_for_stage(stage: DealStage, moment: datetime | None = None) -> datetime | None:
    """When a deal reaching ``stage`` was closed, if it was closed at all."""
    if not is_terminal_deal_stage(stage):
        return None
    return moment if moment is not None else datetime.now(tz=UTC)
