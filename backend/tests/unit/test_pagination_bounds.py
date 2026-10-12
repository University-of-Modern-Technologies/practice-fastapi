"""Every list serves the same pages: from 1 to ``MAX_PAGE``."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from app.core.pagination import MAX_PAGE, ListQuery
from app.modules.audit.schemas import AuditListParams
from app.modules.calls.schemas import CallListParams
from app.modules.contacts.schemas import ContactListParams
from app.modules.deals.schemas import DealListParams
from app.modules.helpdesk.schemas import TicketListParams


@pytest.mark.parametrize(
    "model",
    [
        ListQuery,
        AuditListParams,
        CallListParams,
        ContactListParams,
        DealListParams,
        TicketListParams,
    ],
)
def test_the_last_page_is_the_shared_bound(model: type[BaseModel]) -> None:
    assert model.model_validate({"page": MAX_PAGE}).page == MAX_PAGE  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        model.model_validate({"page": MAX_PAGE + 1})


def test_the_bound_is_one_hundred_pages() -> None:
    assert MAX_PAGE == 100
