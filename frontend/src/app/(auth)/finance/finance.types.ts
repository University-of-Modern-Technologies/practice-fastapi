import type { OrderStatus, StatusMeta } from '@/shared/constants';
import type { CurrencyCode, Id, IsoDate, IsoDateTime, MoneyWire, Timestamps, Versioned } from '@/types/domain';

/* ---------------------------------------------------------------------------
 * MOVES TO `@/shared/constants/enums.ts` — everything down to the next banner.
 *
 * Two dictionaries belong with the thirteen already there, and are written in
 * exactly that file's shape so the block transfers by cutting rather than by
 * being rewritten. They live here only because this module does not own the
 * shared layer; nothing else about them is local.
 * ------------------------------------------------------------------------- */

export const TRANSACTION_DIRECTIONS = ['CREDIT', 'DEBIT'] as const;
export type TransactionDirection = (typeof TRANSACTION_DIRECTIONS)[number];

export const PAYMENT_MATCH_STATUSES = ['UNMATCHED', 'SUGGESTED', 'MATCHED', 'IGNORED'] as const;
export type PaymentMatchStatus = (typeof PAYMENT_MATCH_STATUSES)[number];

export const TRANSACTION_DIRECTION: Readonly<Record<TransactionDirection, StatusMeta>> = {
  CREDIT: { label: 'Надходження', color: 'success' },
  DEBIT: { label: 'Списання', color: 'default' },
};

/**
 * The colours carry the argument of the whole section, so they are not chosen
 * for variety.
 *
 * `UNMATCHED` is `default` and deliberately not `error`: a payment that has not
 * been tied to an order is the state every transaction starts in and the state
 * most of them legitimately stay in. Painted red, a statement of twelve rows
 * would read as twelve faults, and the operator would go looking for a
 * malfunction that is not there.
 *
 * `SUGGESTED` is the only warning here, and it is a warning about a person
 * rather than about the data: it is the one state that will not resolve itself,
 * because the machine has found more than one answer and stopped.
 */
export const PAYMENT_MATCH_STATUS: Readonly<Record<PaymentMatchStatus, StatusMeta>> = {
  UNMATCHED: { label: 'Не зведено', color: 'default' },
  SUGGESTED: { label: 'Потрібен вибір', color: 'warning' },
  MATCHED: { label: 'Зведено', color: 'success' },
  IGNORED: { label: 'Не підлягає зведенню', color: 'default' },
};

/* --------------------------- end of the moving block --------------------- */

/**
 * A bank statement as the API returns it.
 *
 * It carries no `version`, and that is not an omission: nothing in the contract
 * edits a statement. It is imported once, and the records that are then worked
 * on are its transactions.
 */
export interface BankStatement extends Timestamps {
  readonly id: Id;
  /** The bank's own identifier; it is what makes a repeated import idempotent. */
  readonly externalId: string;
  readonly accountLabel: string;
  readonly periodStart: IsoDate;
  readonly periodEnd: IsoDate;
  readonly openingBalance: MoneyWire;
  readonly closingBalance: MoneyWire;
  readonly currency: CurrencyCode;
  readonly importedAt: IsoDateTime;
  readonly importedById: Id;
}

/**
 * One line of a statement.
 *
 * `matchStatus` is the field the whole section is about. A transaction arrives
 * as `UNMATCHED` and may never leave that state — the bank and the order book
 * are two independent records of the same money, and they do not agree by
 * construction. Every screen here is written from that assumption: a
 * discrepancy is the subject matter, not a defect report.
 */
export interface BankTransaction extends Timestamps, Versioned {
  readonly id: Id;
  readonly statementId: Id;
  readonly externalId: string;
  readonly bookedAt: IsoDateTime;
  /** A string on the wire, always. A float would lose cents on the first sum. */
  readonly amount: MoneyWire;
  readonly currency: CurrencyCode;
  readonly direction: TransactionDirection;
  readonly counterpartyName: string;
  readonly counterpartyAccount: string | null;
  /** What the payer wrote on the payment — the main source of reconciliation. */
  readonly reference: string;
  readonly matchStatus: PaymentMatchStatus;
  readonly matchedOrderId: Id | null;
  readonly matchedAt: IsoDateTime | null;
  readonly matchedById: Id | null;
}

/**
 * An order the reconciliation rule put forward for one transaction.
 *
 * The contract says the read of a single transaction answers with "a list of
 * candidates for `SUGGESTED`" and stops there: neither the field that carries
 * the list nor the shape of its elements is written down. This is the shape the
 * card is drawn against, and `readCandidates` below is what keeps a build that
 * answers differently from blanking the page.
 */
export interface MatchCandidate {
  readonly orderId: Id;
  readonly orderNumber: string;
  readonly total: MoneyWire;
  readonly currency: CurrencyCode;
  readonly status: OrderStatus;
  /** Contact the order belongs to, as an identifier; the build sends no name. */
  readonly contactId: Id | null;
  /**
   * When the order was placed — the field the server's window was measured
   * from, so the distance shown beside a candidate is the distance that
   * actually decided anything. Empty when the order was never placed.
   */
  readonly placedAt: IsoDateTime;
}

/**
 * The single transaction as the card reads it: the record plus whatever the
 * build put alongside it.
 */
export interface BankTransactionDetail extends BankTransaction {
  readonly candidates?: readonly MatchCandidate[];
}

/**
 * Pulls the candidate list out of an answer whose shape the contract does not
 * fix, and refuses to guess.
 *
 * A row that is missing the two things the choice is made on — which order it
 * is and what it is worth — is dropped rather than rendered half-drawn: an
 * operator picking between candidates is authorising money, and a line with a
 * blank amount invites a click nobody can justify afterwards.
 */
export const readCandidates = (value: unknown): readonly MatchCandidate[] => {
  if (typeof value !== 'object' || value === null) return [];
  const { candidates } = value as { candidates?: unknown };
  if (!Array.isArray(candidates)) return [];

  return candidates.flatMap((entry): readonly MatchCandidate[] => {
    if (typeof entry !== 'object' || entry === null) return [];
    const row = entry as Partial<MatchCandidate>;
    if (typeof row.orderId !== 'string' || row.orderId === '') return [];
    if (typeof row.total !== 'string') return [];

    return [
      {
        orderId: row.orderId,
        orderNumber: typeof row.orderNumber === 'string' ? row.orderNumber : row.orderId,
        total: row.total,
        currency: typeof row.currency === 'string' ? row.currency : 'USD',
        status: (typeof row.status === 'string' ? row.status : 'CONFIRMED') as OrderStatus,
        contactId: typeof row.contactId === 'string' ? row.contactId : null,
        placedAt: typeof row.placedAt === 'string' ? row.placedAt : '',
      },
    ];
  });
};

/** Period summary: inflow, outflow, and the shares each match state holds. */
export interface FinanceMatchShare {
  readonly status: PaymentMatchStatus;
  readonly count: number;
  readonly amount: MoneyWire;
  /** Share of the window's transactions, in `[0, 1]`, to four decimals. */
  readonly share: number;
}

/**
 * Flat, the way the build sends it. All four states are always present, so a
 * card comparing two periods has rows that line up rather than rows that
 * appear and disappear with the data.
 */
export interface FinanceSummary {
  readonly from: IsoDateTime;
  readonly to: IsoDateTime;
  readonly transactionCount: number;
  readonly inflow: MoneyWire;
  readonly outflow: MoneyWire;
  readonly net: MoneyWire;
  readonly statuses: readonly FinanceMatchShare[];
}

export interface FinanceSummaryQuery {
  readonly from: IsoDateTime;
  readonly to: IsoDateTime;
}

/** What one import did. A statement already known is `skipped`, not a failure. */
export interface StatementImportResult {
  readonly statementId: Id;
  readonly imported: number;
  readonly skipped: number;
}

/**
 * What one batch reconciliation examined and what it decided.
 *
 * `unmatched` is reported as an outcome beside the other two, which is the
 * right way round: a run that leaves eight of twelve rows untied did its job.
 */
export interface ReconcileResult {
  readonly examined: number;
  readonly matched: number;
  readonly suggested: number;
  readonly unmatched: number;
  /** Outgoing money: examined, then filed, because no order will explain it. */
  readonly ignored: number;
}

/** The only columns the API agrees to order by; anything else answers 400. */
export const TRANSACTION_SORT_FIELDS = ['bookedAt', 'amount', 'createdAt'] as const;

export type TransactionSortField = (typeof TRANSACTION_SORT_FIELDS)[number];

export const isTransactionSortField = (
  value: string | undefined,
): value is TransactionSortField =>
  value !== undefined && (TRANSACTION_SORT_FIELDS as readonly string[]).includes(value);

/**
 * Filters this list understands, and the set `useListParams` keeps in the URL.
 * `statementId` has no control of its own: it is how the statement table links
 * to the lines of one import, and the link has to survive a reload.
 */
export const TRANSACTION_FILTERS = [
  'search',
  'statementId',
  'matchStatus',
  'direction',
  'bookedFrom',
  'bookedTo',
  'minAmount',
  'maxAmount',
] as const;

export type TransactionFilter = (typeof TRANSACTION_FILTERS)[number];

export interface TransactionListQuery {
  readonly page?: number;
  readonly pageSize?: number;
  readonly search?: string;
  readonly statementId?: Id;
  readonly matchStatus?: PaymentMatchStatus;
  readonly direction?: TransactionDirection;
  readonly bookedFrom?: IsoDate;
  readonly bookedTo?: IsoDate;
  /** Money, so a string — the same shape every amount crosses the wire in. */
  readonly minAmount?: MoneyWire;
  readonly maxAmount?: MoneyWire;
  readonly sortBy?: TransactionSortField;
  readonly sortOrder?: 'asc' | 'desc';
}

export const STATEMENT_FILTERS = ['search'] as const;

export type StatementFilter = (typeof STATEMENT_FILTERS)[number];

export interface StatementListQuery {
  readonly page?: number;
  readonly pageSize?: number;
  readonly search?: string;
  readonly sortOrder?: 'asc' | 'desc';
}

/**
 * Tying a transaction to an order by hand. The version the card read travels
 * with it: two people working the same unreconciled statement is the ordinary
 * case, not the rare one.
 */
export interface MatchTransactionInput {
  readonly version: number;
  readonly orderId: Id;
}

/** Error codes this module reacts to by name rather than by status alone. */
export const FINANCE_ERROR = {
  transactionNotFound: 'TRANSACTION_NOT_FOUND',
  statementNotFound: 'STATEMENT_NOT_FOUND',
  alreadyMatched: 'TRANSACTION_ALREADY_MATCHED',
  notMatched: 'TRANSACTION_NOT_MATCHED',
  orderNotFound: 'TRANSACTION_ORDER_NOT_FOUND',
  amountMismatch: 'TRANSACTION_AMOUNT_MISMATCH',
  conflict: 'TRANSACTION_CONCURRENT_MODIFICATION',
  duplicateStatement: 'STATEMENT_DUPLICATE_EXTERNAL_ID',
  providerUnavailable: 'BANK_PROVIDER_UNAVAILABLE',
} as const;

/**
 * A refused write names a condition the operator can act on, so each code gets
 * its own sentence instead of a generic «перевірте дані».
 *
 * `TRANSACTION_AMOUNT_MISMATCH` is worded as a question about intent rather
 * than as a fault, because it is the one refusal that arrives when the operator
 * is right and the machine is being careful: they have decided that this
 * payment is that order despite the sums differing, and the server has declined
 * to take their word for it.
 */
export const FINANCE_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  [FINANCE_ERROR.alreadyMatched]: 'Транзакцію вже зведено — спершу зніміть наявне зведення',
  [FINANCE_ERROR.notMatched]: 'Транзакція не зведена — знімати нічого',
  [FINANCE_ERROR.orderNotFound]: 'Такого замовлення вже немає',
  [FINANCE_ERROR.amountMismatch]:
    'Сума транзакції не збігається з підсумком замовлення — зведення відхилено',
  [FINANCE_ERROR.duplicateStatement]: 'Таку виписку вже імпортовано',
  [FINANCE_ERROR.providerUnavailable]:
    'Банк недоступний — показано те, що вже імпортовано раніше',
};
