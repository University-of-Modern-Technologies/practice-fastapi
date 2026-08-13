"""Proves that everything the module knows about a deal stage now lives in
exactly one place: :mod:`app.modules.deals.state`.
"""

from __future__ import annotations

import pytest

from app.db.enums import DealStage
from app.modules.deals.state import deal_state
from app.modules.deals.transition import ALLOWED_DEAL_STAGE_TRANSITIONS

#: The historical table, kept here only as a fixed point to compare the
#: single-source-of-truth states against.
HISTORICAL_TRANSITIONS: dict[DealStage, set[DealStage]] = {
    DealStage.LEAD: {DealStage.QUALIFIED},
    DealStage.QUALIFIED: {DealStage.PROPOSAL},
    DealStage.PROPOSAL: {DealStage.WON, DealStage.LOST},
    DealStage.WON: set(),
    DealStage.LOST: set(),
}


class TestDealStateRegistry:
    @pytest.mark.parametrize("stage", list(DealStage))
    def test_has_exactly_one_state_per_stage(self, stage: DealStage) -> None:
        assert deal_state(stage).stage is stage

    @pytest.mark.parametrize("stage", list(DealStage))
    def test_carries_the_same_transitions_as_the_historical_table(self, stage: DealStage) -> None:
        assert set(deal_state(stage).allowed_transitions) == HISTORICAL_TRANSITIONS[stage]
        assert set(ALLOWED_DEAL_STAGE_TRANSITIONS[stage]) == HISTORICAL_TRANSITIONS[stage]

    @pytest.mark.parametrize("probability", [0, 1, 50, 99, 100])
    def test_accepts_exactly_100_for_won_and_rejects_everything_else(
        self, probability: int
    ) -> None:
        assert deal_state(DealStage.WON).is_valid_probability(probability) is (probability == 100)

    @pytest.mark.parametrize("probability", [0, 1, 50, 99, 100])
    def test_accepts_exactly_0_for_lost_and_rejects_everything_else(self, probability: int) -> None:
        assert deal_state(DealStage.LOST).is_valid_probability(probability) is (probability == 0)

    @pytest.mark.parametrize("stage", [DealStage.LEAD, DealStage.QUALIFIED, DealStage.PROPOSAL])
    def test_rejects_100_for_every_open_stage(self, stage: DealStage) -> None:
        assert deal_state(stage).is_valid_probability(100) is False
        for probability in (0, 1, 50, 99):
            assert deal_state(stage).is_valid_probability(probability) is True
