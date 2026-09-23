import { ApiError, http, listQuery, type Page, type QueryValue } from '@/shared/api';
import type { ListParams } from '@/shared/hooks';
import type { Id } from '@/types/domain';
import { readAmountFilter } from './finance.validation';
import {
  FINANCE_ERROR,
  PAYMENT_MATCH_STATUSES,
  TRANSACTION_DIRECTIONS,
  isTransactionSortField,
  type BankStatement,
  type BankTransaction,
  type BankTransactionDetail,
  type FinanceSummary,
  type FinanceSummaryQuery,
  type MatchTransactionInput,
  type ReconcileResult,
  type StatementFilter,
  type StatementImportResult,
  type StatementListQuery,
  type TransactionFilter,
  type TransactionListQuery,
} from './finance.types';

const ROUTES = {
  statements: '/finance/statements',
  import: '/finance/statements/import',
  transactions: '/finance/transactions',
  transaction: (id: Id): string => `/finance/transactions/${id}`,
  match: (id: Id): string => `/finance/transactions/${id}/match`,
  reconcile: '/finance/reconcile',
  summary: '/finance/summary',
} as const;

const SEARCH_MAX_LENGTH = 64;

/**
 * Turns the query string state into the shape the API expects. Every filter is
 * text in the URL, so a hand-edited link has to be narrowed down here — an
 * unknown match state, a sort column the API does not know or an amount that is
 * not an amount would otherwise turn the whole page into a 400.
 *
 * The two bounds are spread in after the builder rather than run through it:
 * they are money, and money is neither an integer nor free text. Passing them
 * as text is what `orders` does with `minTotal`, and it is why `minTotal=багато`
 * there reaches the server.
 */
export const toTransactionListQuery = (
  params: ListParams<TransactionFilter>,
): TransactionListQuery => {
  const base = listQuery(params)
    .text('search', { maxLength: SEARCH_MAX_LENGTH })
    .text('statementId')
    .oneOf('matchStatus', PAYMENT_MATCH_STATUSES)
    .oneOf('direction', TRANSACTION_DIRECTIONS)
    .text('bookedFrom')
    .text('bookedTo')
    .sort(isTransactionSortField)
    .build<TransactionListQuery>();

  const minAmount = readAmountFilter(params.minAmount);
  const maxAmount = readAmountFilter(params.maxAmount);

  return {
    ...base,
    ...(minAmount === undefined ? {} : { minAmount }),
    ...(maxAmount === undefined ? {} : { maxAmount }),
  };
};

export const toStatementListQuery = (params: ListParams<StatementFilter>): StatementListQuery =>
  listQuery(params)
    .text('search', { maxLength: SEARCH_MAX_LENGTH })
    .build<StatementListQuery>();

/**
 * Not every API build serves the finance section, and the client is never told
 * which one it is talking to: a build without the module answers 404 on the
 * very first read. That is "this section is not here", not "the list failed",
 * and it must not be reported as a failure.
 *
 * A dead transport is deliberately not counted, and neither is a missing record
 * of either kind: sending an operator to an administrator because one statement
 * has been deleted would be the wrong errand.
 */
export const isModuleUnavailable = (error: unknown): boolean =>
  error instanceof ApiError &&
  error.status === 404 &&
  error.code !== FINANCE_ERROR.transactionNotFound &&
  error.code !== FINANCE_ERROR.statementNotFound;

/**
 * The bank sits behind the import action only. Its being down says nothing
 * about the statements already pulled, so the page that shows this names the
 * bank rather than blanking the table.
 */
export const isProviderUnavailable = (error: unknown): boolean =>
  error instanceof ApiError && error.code === FINANCE_ERROR.providerUnavailable;

/**
 * A 409 carries two different answers here, exactly as it does in `orders`.
 * `TRANSACTION_CONCURRENT_MODIFICATION` means somebody saved first and a
 * re-read fixes it; `TRANSACTION_ALREADY_MATCHED` means the domain refused the
 * request itself, and offering a re-read would send the operator to do
 * something that cannot help.
 */
export const isVersionConflict = (error: unknown): boolean =>
  error instanceof ApiError &&
  error.isConflict &&
  error.code !== FINANCE_ERROR.alreadyMatched &&
  error.code !== FINANCE_ERROR.notMatched;

/**
 * The only place that knows the shape of the finance endpoints. It holds no
 * React, so its request paths and bodies can be asserted without a DOM.
 */
export const FinanceService = {
  statements: (query: StatementListQuery, signal?: AbortSignal): Promise<Page<BankStatement>> =>
    http.get<Page<BankStatement>>(ROUTES.statements, {
      params: query as Readonly<Record<string, QueryValue>>,
      ...(signal ? { signal } : {}),
    }),

  /**
   * Pulls a statement through the bank stub. The contract describes no request
   * body, so none is sent.
   */
  importStatement: (): Promise<StatementImportResult> =>
    http.post<StatementImportResult>(ROUTES.import),

  transactions: (
    query: TransactionListQuery,
    signal?: AbortSignal,
  ): Promise<Page<BankTransaction>> =>
    http.get<Page<BankTransaction>>(ROUTES.transactions, {
      params: query as Readonly<Record<string, QueryValue>>,
      ...(signal ? { signal } : {}),
    }),

  /**
   * Reads one transaction. The candidate list travels with it — this is the
   * only endpoint that carries it, so the card cannot offer a choice without
   * this read having happened.
   */
  getById: (id: Id, signal?: AbortSignal): Promise<BankTransactionDetail> =>
    http.get<BankTransactionDetail>(ROUTES.transaction(id), { ...(signal ? { signal } : {}) }),

  /** Tying a payment to an order by hand; the version is the one the card read. */
  match: (id: Id, input: MatchTransactionInput): Promise<BankTransaction> =>
    http.post<BankTransaction>(ROUTES.match(id), {
      version: input.version,
      orderId: input.orderId,
    }),

  /**
   * Undoing that. The version travels in the query string — a DELETE carries no
   * body, and the contract does not say this endpoint takes one. It is sent
   * because the module is under optimistic concurrency and publishes its own
   * conflict code: an unmatch that ignored the version would be the one write
   * in the section that could quietly undo somebody else's decision.
   */
  unmatch: (id: Id, version: number): Promise<BankTransaction> =>
    http.delete<BankTransaction>(ROUTES.match(id), { params: { version } }),

  /** Batch reconciliation over what has been imported. */
  reconcile: (): Promise<ReconcileResult> => http.post<ReconcileResult>(ROUTES.reconcile),

  summary: (query: FinanceSummaryQuery, signal?: AbortSignal): Promise<FinanceSummary> =>
    http.get<FinanceSummary>(ROUTES.summary, {
      params: { from: query.from, to: query.to },
      ...(signal ? { signal } : {}),
    }),
};
