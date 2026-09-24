'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Page } from '@/shared/api';
import type { Id } from '@/types/domain';
import { FinanceService } from './finance.service';
import type {
  BankStatement,
  BankTransaction,
  BankTransactionDetail,
  FinanceSummary,
  FinanceSummaryQuery,
  MatchTransactionInput,
  ReconcileResult,
  StatementImportResult,
  StatementListQuery,
  TransactionListQuery,
} from './finance.types';

/**
 * Hierarchical keys let a write invalidate exactly what it touched.
 *
 * One branch, not two, even though the section reads two collections: matching
 * a transaction changes what the summary says about the shares of each state,
 * and an import changes both the statement list and the transaction list. A
 * separate `summary` root would have to be remembered at every write, and the
 * one that forgot it would leave a chart quietly contradicting the table under
 * it.
 *
 * The live channel is meant to invalidate through these same factories — the
 * resolver for a `transaction.*` or `statement.*` event reads them rather than
 * spelling the keys out a second time. Wiring those events into that resolver
 * belongs to whoever owns the shared realtime layer; this module only publishes
 * the keys.
 */
export const financeKeys = {
  all: ['finance'] as const,
  statements: () => [...financeKeys.all, 'statements'] as const,
  statementList: (params: StatementListQuery) => [...financeKeys.statements(), params] as const,
  transactions: () => [...financeKeys.all, 'transactions'] as const,
  transactionList: (params: TransactionListQuery) =>
    [...financeKeys.transactions(), 'list', params] as const,
  transactionDetails: () => [...financeKeys.transactions(), 'detail'] as const,
  transaction: (id: Id) => [...financeKeys.transactionDetails(), id] as const,
  summaries: () => [...financeKeys.all, 'summary'] as const,
  summary: (params: FinanceSummaryQuery) => [...financeKeys.summaries(), params] as const,
};

export const useStatements = (query: StatementListQuery) =>
  useQuery<Page<BankStatement>>({
    queryKey: financeKeys.statementList(query),
    queryFn: ({ signal }) => FinanceService.statements(query, signal),
    // Paging swaps one page for the next in place instead of blanking the table.
    placeholderData: keepPreviousData,
  });

export const useTransactions = (query: TransactionListQuery) =>
  useQuery<Page<BankTransaction>>({
    queryKey: financeKeys.transactionList(query),
    queryFn: ({ signal }) => FinanceService.transactions(query, signal),
    placeholderData: keepPreviousData,
  });

export const useTransaction = (id: Id) =>
  useQuery<BankTransactionDetail>({
    queryKey: financeKeys.transaction(id),
    queryFn: ({ signal }) => FinanceService.getById(id, signal),
    enabled: id !== '',
  });

export const useFinanceSummary = (query: FinanceSummaryQuery, options: { enabled: boolean }) =>
  useQuery<FinanceSummary>({
    queryKey: financeKeys.summary(query),
    queryFn: ({ signal }) => FinanceService.summary(query, signal),
    enabled: options.enabled,
  });

/**
 * Pulling a statement from the bank. A mutation rather than a query even though
 * it reads from somewhere else: it creates records, and it must happen when the
 * operator asks for it and not because a component mounted.
 */
export const useImportStatement = () => {
  const queryClient = useQueryClient();

  return useMutation<StatementImportResult, unknown, void>({
    mutationFn: () => FinanceService.importStatement(),
    onSuccess: (result) => {
      // Nothing new means nothing to re-read: a refetch after every repeat
      // import would restart the open table for no change at all.
      if (result.imported > 0) void queryClient.invalidateQueries({ queryKey: financeKeys.all });
    },
  });
};

/**
 * Batch reconciliation. Every counter it returns can be non-zero at once, and
 * any of them being non-zero means some row somewhere changed state — so the
 * whole branch goes rather than a list of individually named entries.
 */
export const useReconcile = () => {
  const queryClient = useQueryClient();

  return useMutation<ReconcileResult, unknown, void>({
    mutationFn: () => FinanceService.reconcile(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: financeKeys.all });
    },
  });
};

/**
 * The card is refreshed from the answer, which carries the bumped version —
 * but only the record itself. The candidate list is not part of a write's
 * response, so the entry is invalidated as well rather than replaced: leaving
 * the old candidates cached would keep offering a choice that has been made.
 */
const useTransactionWriter = <TInput>(id: Id, run: (input: TInput) => Promise<BankTransaction>) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: financeKeys.transaction(id) });
      void queryClient.invalidateQueries({ queryKey: financeKeys.transactions() });
      // Matching one payment moves it between the shares the summary reports.
      void queryClient.invalidateQueries({ queryKey: financeKeys.summaries() });
    },
  });
};

export const useMatchTransaction = (id: Id) =>
  useTransactionWriter<MatchTransactionInput>(id, (input) => FinanceService.match(id, input));

export const useUnmatchTransaction = (id: Id) =>
  useTransactionWriter<number>(id, (version) => FinanceService.unmatch(id, version));
