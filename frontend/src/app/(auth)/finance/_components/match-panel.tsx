'use client';

import { Alert, Button, Card, Space, Typography } from 'antd';
import { Link2, Unlink } from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';
import { DateValue, PermissionGate } from '@/components';
import { useHasPermission, useMutationFeedback } from '@/shared/hooks';
import { useMatchTransaction, useUnmatchTransaction } from '../finance.queries';
import { isVersionConflict } from '../finance.service';
import {
  FINANCE_ERROR_MESSAGES,
  readCandidates,
  type BankTransactionDetail,
} from '../finance.types';
import { ManualMatchModal } from './manual-match-modal';
import { MatchCandidates } from './match-candidates';

interface MatchPanelProps {
  readonly transaction: BankTransactionDetail;
  /** Raised so the card can show its one conflict alert and offer the re-read. */
  readonly onConflict: (error: unknown) => boolean;
}

/**
 * What can be done with one payment, according to where it currently stands.
 *
 * The four states are genuinely four different situations and not four shades
 * of one, so none of them is drawn as a degraded version of `MATCHED`:
 *
 * - `MATCHED` — settled; the only move is to undo it.
 * - `SUGGESTED` — the rule found several answers and stopped. A person decides.
 * - `UNMATCHED` — no answer was found. This is a working state, said in those
 *   words, because the bank and the order book are two independent records of
 *   the same money and they do not agree by construction. A payment nobody has
 *   tied to an order is not a fault report.
 * - `IGNORED` — declared outside reconciliation altogether.
 */
export function MatchPanel({ transaction, onConflict }: MatchPanelProps) {
  const { reportSuccess, reportFailureWith } = useMutationFeedback();
  const canWrite = useHasPermission('finance', 'write');

  const [isPickingOther, setIsPickingOther] = useState(false);
  const [pickingOrderId, setPickingOrderId] = useState<string | null>(null);

  const match = useMatchTransaction(transaction.id);
  const unmatch = useUnmatchTransaction(transaction.id);

  const reportFailure = reportFailureWith(FINANCE_ERROR_MESSAGES);

  const handleFailure = (error: unknown): void => {
    // Only a lost race is worth a re-read. A refusal the domain made about the
    // request itself leaves the record on screen current, and offering to
    // reload it would send the operator to do something that cannot help.
    if (isVersionConflict(error) && onConflict(error)) return;
    reportFailure(error);
  };

  const onPick = (orderId: string): void => {
    setPickingOrderId(orderId);
    match.mutate(
      { version: transaction.version, orderId },
      {
        onSuccess: () => {
          reportSuccess('Платіж зведено із замовленням');
          setPickingOrderId(null);
        },
        onError: (error: unknown) => {
          setPickingOrderId(null);
          handleFailure(error);
        },
      },
    );
  };

  const onUnmatch = (): void => {
    unmatch.mutate(transaction.version, {
      onSuccess: () => reportSuccess('Зведення знято'),
      onError: handleFailure,
    });
  };

  const manualMatchAction = (
    <PermissionGate resource="finance" action="write" fallback={null}>
      <Button icon={<Link2 size={16} />} onClick={() => setIsPickingOther(true)}>
        Звести вручну
      </Button>
    </PermissionGate>
  );

  const modal = (
    <ManualMatchModal
      transaction={isPickingOther ? transaction : null}
      onCancel={() => setIsPickingOther(false)}
      onMatched={() => setIsPickingOther(false)}
      onConflict={onConflict}
    />
  );

  if (transaction.matchStatus === 'MATCHED') {
    return (
      <Card
        title="Зведення"
        className="mb-4"
        extra={
          <PermissionGate resource="finance" action="write" fallback={null}>
            <Button
              danger
              icon={<Unlink size={16} />}
              loading={unmatch.isPending}
              onClick={onUnmatch}
            >
              Зняти зведення
            </Button>
          </PermissionGate>
        }
      >
        <Space direction="vertical" size={4}>
          <Typography.Text>
            Платіж зведено із замовленням{' '}
            {transaction.matchedOrderId === null ? (
              <Typography.Text type="secondary">(замовлення не назване)</Typography.Text>
            ) : (
              <Link href={`/orders/${transaction.matchedOrderId}`}>
                {transaction.matchedOrderId}
              </Link>
            )}
          </Typography.Text>
          <Typography.Text type="secondary">
            Зведено: <DateValue value={transaction.matchedAt} withTime />
          </Typography.Text>
        </Space>
      </Card>
    );
  }

  if (transaction.matchStatus === 'SUGGESTED') {
    const candidates = readCandidates(transaction);

    // The state says there are several answers, and the read came back without
    // them. Saying so plainly is the only honest move: the choice this state
    // exists for cannot be made here, and pretending the payment is simply
    // untied would hide that something is missing.
    if (candidates.length === 0) {
      return (
        <>
          <Card title="Зведення" className="mb-4" extra={manualMatchAction}>
            <Alert
              type="warning"
              showIcon
              message="Кандидатів не отримано"
              description="Платіж позначено як такий, що потребує вибору, але список кандидатів у відповіді відсутній. Обрати замовлення можна вручну."
            />
          </Card>
          {modal}
        </>
      );
    }

    return (
      <>
        <MatchCandidates
          transaction={transaction}
          candidates={candidates}
          onPick={(candidate) => onPick(candidate.orderId)}
          pickingOrderId={pickingOrderId}
          canWrite={canWrite}
          onPickOther={() => setIsPickingOther(true)}
        />
        {modal}
      </>
    );
  }

  if (transaction.matchStatus === 'IGNORED') {
    return (
      <>
        <Card title="Зведення" className="mb-4" extra={manualMatchAction}>
          <Typography.Text type="secondary">
            Платіж виведено зі зведення — його не порівнюють із замовленнями.
          </Typography.Text>
        </Card>
        {modal}
      </>
    );
  }

  return (
    <>
      <Card title="Зведення" className="mb-4" extra={manualMatchAction}>
        {/*
          The sentence this whole section turns on. A payment with no order
          behind it is not an error and is not missing data: the bank and the
          order book are two independent records, and most statements contain
          money that belongs to neither side of a sale. Worded as a problem,
          this screen would send somebody looking for a malfunction every time
          the rent is paid.
        */}
        <Typography.Paragraph className="mb-2">
          Цей платіж не зведено із замовленням. Це робочий стан, а не помилка: виписка банку й книга
          замовлень — два незалежні записи, і збігаються вони не завжди.
        </Typography.Paragraph>
        <Typography.Text type="secondary">
          {canWrite
            ? 'Якщо ви знаєте, якого замовлення стосується платіж, зведіть його вручну.'
            : 'Звести платіж може той, хто має право на зміни у фінансах.'}
        </Typography.Text>
      </Card>
      {modal}
    </>
  );
}
