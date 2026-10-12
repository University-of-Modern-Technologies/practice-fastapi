"""Bounds every report window shares."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.reporting import MAX_REPORT_WINDOW_DAYS
from app.modules.analytics.kyiv_time import DEFAULT_KYIV_WINDOW_FROM, default_kyiv_window_to


def test_the_default_window_fits_under_the_ceiling_for_years() -> None:
    far_ahead = default_kyiv_window_to(datetime(2030, 12, 31, tzinfo=UTC))

    assert far_ahead - DEFAULT_KYIV_WINDOW_FROM <= timedelta(days=MAX_REPORT_WINDOW_DAYS)
