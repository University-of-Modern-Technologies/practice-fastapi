'use client';

import { Button, Card, List, Space, Tag, Typography } from 'antd';
import Link from 'next/link';
import { MoneyValue, StatusTag } from '@/components';
import { ORDER_STATUS } from '@/shared/constants';
import { describeMatch, type MatchGround } from '../finance.validation';
import type { BankTransaction, MatchCandidate } from '../finance.types';

interface MatchCandidatesProps {
  readonly transaction: BankTransaction;
  readonly candidates: readonly MatchCandidate[];
  readonly onPick: (candidate: MatchCandidate) => void;
  readonly pickingOrderId: string | null;
  /** Absent for a reader: the list is then evidence rather than a choice. */
  readonly canWrite: boolean;
  /** Opens the free picker for the case where none of these is the answer. */
  readonly onPickOther: () => void;
}

const GROUND_COLOR: Readonly<Record<MatchGround['kind'], string>> = {
  evidence: 'green',
  caution: 'orange',
  neutral: 'default',
};

/**
 * Why this order is here, said in the order that matters: what made it an
 * answer first, what should slow the click down second.
 */
function Grounds({ grounds }: { readonly grounds: readonly MatchGround[] }) {
  const sorted = [...grounds].sort((left, right) => {
    const weight = { evidence: 0, caution: 1, neutral: 2 } as const;
    return weight[left.kind] - weight[right.kind];
  });

  return (
    <Space wrap size={[4, 4]} className="mt-2">
      {sorted.map((ground) => (
        <Tag key={ground.key} color={GROUND_COLOR[ground.kind]}>
          {ground.text}
        </Tag>
      ))}
    </Space>
  );
}

/**
 * The hardest screen in the section, and the reason it exists at all.
 *
 * `SUGGESTED` means the rule ran to completion and came back with more than one
 * answer — so the machine has already done everything it can, and a person now
 * has to decide. A bare list of order numbers would make that decision blind:
 * every row looks equally plausible, and the operator picks the first one.
 * What each row therefore carries is the evidence the rule acted on — the
 * number found in the payment reference, the payer's name matching the
 * contact, the sums agreeing or differing and by how much, how far apart the
 * payment and the order are in time.
 *
 * None of that evidence is recomputed policy. The tolerance, the window and the
 * order statuses are the server's constants; this panel reports differences and
 * distances, and leaves every verdict where it belongs.
 */
export function MatchCandidates({
  transaction,
  candidates,
  onPick,
  pickingOrderId,
  canWrite,
  onPickOther,
}: MatchCandidatesProps) {
  return (
    <Card
      title="Кандидати на зведення"
      className="mb-4"
      extra={
        canWrite ? (
          <Button size="small" onClick={onPickOther}>
            Жоден не підходить
          </Button>
        ) : null
      }
    >
      <Typography.Paragraph type="secondary">
        {canWrite
          ? `Правило знайшло замовлень: ${candidates.length}. Автоматично звести не можна — вибір за людиною. Нижче — те, на чому правило зупинилося на кожному з них.`
          : `Правило знайшло замовлень: ${candidates.length}. Вибір робить той, хто має право на зміни у фінансах.`}
      </Typography.Paragraph>

      <List
        itemLayout="vertical"
        dataSource={[...candidates]}
        rowKey={(candidate) => candidate.orderId}
        renderItem={(candidate) => (
          <List.Item
            key={candidate.orderId}
            extra={
              canWrite ? (
                <Button
                  type="primary"
                  loading={pickingOrderId === candidate.orderId}
                  onClick={() => onPick(candidate)}
                >
                  Звести з цим
                </Button>
              ) : null
            }
          >
            <Space wrap align="center">
              <Link href={`/orders/${candidate.orderId}`}>
                <Typography.Text strong>{candidate.orderNumber}</Typography.Text>
              </Link>
              <StatusTag dictionary={ORDER_STATUS} value={candidate.status} />
              <MoneyValue value={candidate.total} currency={candidate.currency} showCurrency />
              {candidate.contactId === null ? null : (
                <Link href={`/contacts/${candidate.contactId}`}>
                  <Typography.Text type="secondary">Клієнт</Typography.Text>
                </Link>
              )}
            </Space>

            <Grounds grounds={describeMatch(transaction, candidate)} />
          </List.Item>
        )}
      />
    </Card>
  );
}
