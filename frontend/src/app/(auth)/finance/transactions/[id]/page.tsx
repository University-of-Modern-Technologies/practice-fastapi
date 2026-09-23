'use client';

import { Button, Card, Descriptions, Result, Space, Typography } from 'antd';
import Link from 'next/link';
import { use } from 'react';
import {
  BackButton,
  ConflictAlert,
  CopyableValue,
  DateValue,
  FormPageSkeleton,
  MoneyValue,
  PageHeader,
  PermissionGate,
  StatusTag,
} from '@/components';
import { ApiError } from '@/shared/api';
import { useVersionConflict } from '@/shared/hooks';
import { MatchPanel } from '../../_components';
import { useTransaction } from '../../finance.queries';
import {
  PAYMENT_MATCH_STATUS,
  TRANSACTION_DIRECTION,
  type BankTransactionDetail,
} from '../../finance.types';

const Meta = ({ transaction }: { readonly transaction: BankTransactionDetail }) => (
  <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }} bordered>
    <Descriptions.Item label="Ідентифікатор у банку">
      <CopyableValue value={transaction.externalId} />
    </Descriptions.Item>
    <Descriptions.Item label="Ідентифікатор">
      <CopyableValue value={transaction.id} />
    </Descriptions.Item>
    <Descriptions.Item label="Напрямок">
      <StatusTag dictionary={TRANSACTION_DIRECTION} value={transaction.direction} />
    </Descriptions.Item>
    <Descriptions.Item label="Сума">
      <MoneyValue value={transaction.amount} currency={transaction.currency} showCurrency />
    </Descriptions.Item>
    <Descriptions.Item label="Контрагент">{transaction.counterpartyName}</Descriptions.Item>
    <Descriptions.Item label="Рахунок контрагента">
      {transaction.counterpartyAccount === null ? (
        <Typography.Text type="secondary">—</Typography.Text>
      ) : (
        <CopyableValue value={transaction.counterpartyAccount} />
      )}
    </Descriptions.Item>
    <Descriptions.Item label="Проведено">
      <DateValue value={transaction.bookedAt} withTime />
    </Descriptions.Item>
    <Descriptions.Item label="Виписка">
      <Link href={`/finance/transactions?statementId=${transaction.statementId}`}>
        Інші платежі цієї виписки
      </Link>
    </Descriptions.Item>
  </Descriptions>
);

/**
 * The card of one payment.
 *
 * The reference gets a block of its own rather than a cell in the table above,
 * because it is the text the reconciliation rule reads: an operator working out
 * why nothing matched is reading exactly what the matcher read, and a truncated
 * line would hide the answer.
 */
function TransactionCard({
  transaction,
  onReload,
  isReloading,
}: {
  readonly transaction: BankTransactionDetail;
  readonly onReload: () => unknown;
  readonly isReloading: boolean;
}) {
  const { hasConflict, handleError, clearConflict } = useVersionConflict();

  return (
    <>
      <PageHeader
        title={`${transaction.counterpartyName}`}
        description="Платіж із банківської виписки"
        actions={
          <Space wrap>
            <StatusTag dictionary={TRANSACTION_DIRECTION} value={transaction.direction} />
            <StatusTag dictionary={PAYMENT_MATCH_STATUS} value={transaction.matchStatus} />
          </Space>
        }
      />

      <ConflictAlert
        open={hasConflict}
        isReloading={isReloading}
        onReload={() => {
          clearConflict();
          void onReload();
        }}
      />

      <div className="mb-4">
        <Meta transaction={transaction} />
      </div>

      <Card
        title="Призначення платежу"
        className="mb-4"
        extra={<BackButton href="/finance/transactions" />}
      >
        <Typography.Paragraph className="mb-0">{transaction.reference}</Typography.Paragraph>
      </Card>

      <MatchPanel transaction={transaction} onConflict={handleError} />
    </>
  );
}

export default function FinanceTransactionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: transaction, isLoading, isError, error, isFetching, refetch } = useTransaction(id);

  if (isLoading) return <FormPageSkeleton />;

  if (isError || transaction === undefined) {
    const notFound = !(error instanceof ApiError) || error.status === 404;

    return (
      <Result
        status={notFound ? '404' : 'error'}
        title={notFound ? 'Платіж не знайдено' : 'Не вдалося прочитати платіж'}
        subTitle={
          notFound
            ? 'Запис міг бути видалений, або він недоступний вашій області доступу.'
            : 'Спробуйте ще раз або зверніться до адміністратора.'
        }
        extra={
          <Link href="/finance/transactions">
            <Button type="primary">До переліку платежів</Button>
          </Link>
        }
      />
    );
  }

  return (
    <PermissionGate resource="finance" action="read">
      <TransactionCard
        transaction={transaction}
        onReload={refetch}
        isReloading={isFetching}
      />
    </PermissionGate>
  );
}
