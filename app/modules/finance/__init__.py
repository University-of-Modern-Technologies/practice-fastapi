"""The ledger: what the bank says arrived, and what it turned out to be for.

This is the one module in the system where the data does not add up, and where
that is the normal state rather than a fault. A bank reports money; an order
book records what was owed; the two are connected by nothing more reliable
than what a payer typed into a reference field. Reconciliation is therefore a
rule with a tolerance and a window, not a lookup, and its honest outcomes are
three: one order fits, several might, or none does.

Everything a record here states about itself comes from the bank and is never
editable. What people may state is what a line *means* — which order it
settles — and that is the whole write surface: match, unmatch, and the batch
run of the rule.

The import is idempotent by identity: ``externalId`` is unique on both tables,
so pulling the same feed again files nothing and says so. Everything the
module needs in order to run — including the bank — is in this repository, so
a fresh checkout imports, reconciles and reports with no account and no
network.

Mount with ``create_finance_router()`` under ``/api/v1/finance``.
"""

from __future__ import annotations

from app.modules.finance.matching import (
    MATCH_AMOUNT_TOLERANCE,
    MATCH_WINDOW_DAYS,
    MATCHABLE_ORDER_STATUSES,
    MatchCandidate,
    MatchSubject,
    outcome_for,
    select_candidates,
)
from app.modules.finance.provider import (
    BankProvider,
    ProviderStatement,
    ProviderTransaction,
    bank_provider_unavailable_error,
)
from app.modules.finance.router import (
    FinanceServiceDep,
    create_finance_router,
    get_bank_provider,
    get_finance_service,
)
from app.modules.finance.schemas import (
    BankStatementOut,
    BankTransactionDetailOut,
    BankTransactionOut,
    FinanceSummaryOut,
    FinanceSummaryParams,
    ImportStatementOut,
    MatchCandidateOut,
    MatchStatusShare,
    MatchTransactionRequest,
    ReconcileOut,
    StatementListParams,
    TransactionListParams,
)
from app.modules.finance.service import (
    RECONCILE_BATCH_SIZE,
    FinanceService,
    to_statement_out,
    to_transaction_out,
)
from app.modules.finance.stub_provider import (
    STUB_STATEMENT_EXTERNAL_ID,
    STUB_TRANSACTION_COUNT,
    StubBankProvider,
    create_stub_bank_provider,
    stub_statement,
)
from app.modules.finance.types import FinanceAccess, StatementSortField, TransactionSortField

__all__ = [
    "MATCHABLE_ORDER_STATUSES",
    "MATCH_AMOUNT_TOLERANCE",
    "MATCH_WINDOW_DAYS",
    "RECONCILE_BATCH_SIZE",
    "STUB_STATEMENT_EXTERNAL_ID",
    "STUB_TRANSACTION_COUNT",
    "BankProvider",
    "BankStatementOut",
    "BankTransactionDetailOut",
    "BankTransactionOut",
    "FinanceAccess",
    "FinanceService",
    "FinanceServiceDep",
    "FinanceSummaryOut",
    "FinanceSummaryParams",
    "ImportStatementOut",
    "MatchCandidate",
    "MatchCandidateOut",
    "MatchStatusShare",
    "MatchSubject",
    "MatchTransactionRequest",
    "ProviderStatement",
    "ProviderTransaction",
    "ReconcileOut",
    "StatementListParams",
    "StatementSortField",
    "StubBankProvider",
    "TransactionListParams",
    "TransactionSortField",
    "bank_provider_unavailable_error",
    "create_finance_router",
    "create_stub_bank_provider",
    "get_bank_provider",
    "get_finance_service",
    "outcome_for",
    "select_candidates",
    "stub_statement",
    "to_statement_out",
    "to_transaction_out",
]
