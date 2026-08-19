"""The deal pipeline, gathered into one object per stage.

Grouping the transition table and the probability rule inside a single
hierarchy is what keeps adding a stage from being a change that touches two
unrelated files, only one of which a reviewer happens to look at.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.db.enums import DealStage

__all__ = ["DealState", "deal_state"]

#: Certainty a closed deal's outcome implies. Kept local to this module rather
#: than imported from ``transition.py``, which imports states from here.
_WON_PROBABILITY = 100
_LOST_PROBABILITY = 0


class DealState(ABC):
    """One stage of the pipeline, and everything that follows from it."""

    #: The stage this object describes.
    stage: DealStage
    #: Stages reachable from here.
    allowed_transitions: tuple[DealStage, ...]

    @abstractmethod
    def is_valid_probability(self, probability: int) -> bool:
        """Whether ``probability`` is compatible with this stage.

        The generic integer/0-100 range check is stage-independent and lives
        in :mod:`app.modules.deals.transition`; this only encodes what a
        *closed* outcome demands: ``WON`` is certain to have happened, ``LOST``
        is certain not to have, and every open stage is merely an estimate
        that must stop short of that certainty.
        """


class _OpenStage(DealState):
    """A deal that has not closed may not claim the certainty a closed one
    reports."""

    def is_valid_probability(self, probability: int) -> bool:
        return probability != _WON_PROBABILITY


class _Lead(_OpenStage):
    stage = DealStage.LEAD
    allowed_transitions = (DealStage.QUALIFIED,)


class _Qualified(_OpenStage):
    stage = DealStage.QUALIFIED
    allowed_transitions = (DealStage.PROPOSAL,)


class _Proposal(_OpenStage):
    stage = DealStage.PROPOSAL
    allowed_transitions = (DealStage.WON, DealStage.LOST)


class _Won(DealState):
    """Final: a won deal is certain to have happened."""

    stage = DealStage.WON
    allowed_transitions = ()

    def is_valid_probability(self, probability: int) -> bool:
        return probability == _WON_PROBABILITY


class _Lost(DealState):
    """Final: a lost deal is certain not to have happened."""

    stage = DealStage.LOST
    allowed_transitions = ()

    def is_valid_probability(self, probability: int) -> bool:
        return probability == _LOST_PROBABILITY


_STATES: dict[DealStage, DealState] = {
    DealStage.LEAD: _Lead(),
    DealStage.QUALIFIED: _Qualified(),
    DealStage.PROPOSAL: _Proposal(),
    DealStage.WON: _Won(),
    DealStage.LOST: _Lost(),
}


def deal_state(stage: DealStage) -> DealState:
    """The single object that knows everything about ``stage``."""
    return _STATES[stage]
