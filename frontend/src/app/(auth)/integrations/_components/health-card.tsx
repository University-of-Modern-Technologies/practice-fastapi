'use client';

import { Alert, Button, Card, Descriptions, Skeleton, Space, Tag, Typography } from 'antd';
import { DateValue, StatusTag } from '@/components';
import { formatCount } from '@/lib/number';
import { CIRCUIT_STATE } from '@/shared/constants';
import type { DeliveryHealth } from '../integrations.types';

interface HealthCardProps {
  readonly health: DeliveryHealth | undefined;
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly isFetching: boolean;
  readonly onRefresh: () => void;
}

/** Says what an open breaker means for the operator, not what it means in code. */
const CIRCUIT_EXPLANATION: Readonly<Record<string, string>> = {
  closed: 'Запити до служби доставки проходять як звичайно.',
  'half-open':
    'Іде перевірка: пропускається один пробний запит. Якщо він вдасться, роботу буде відновлено.',
  open: 'Зовнішній сервіс не відповідає, запити тимчасово не йдуть. Розрахунок і створення відправлень зараз недоступні.',
};

const alertType = (state: string): 'success' | 'warning' | 'error' =>
  state === 'closed' ? 'success' : state === 'open' ? 'error' : 'warning';

/**
 * The state of the circuit breaker is the first thing on the page: whether a
 * failed quote means a typo or a dependency that stopped answering is decided
 * here, before the operator retries the form five times.
 */
export function HealthCard({ health, isLoading, isError, isFetching, onRefresh }: HealthCardProps) {
  return (
    <Card
      size="small"
      title="Стан зовнішньої служби доставки"
      extra={
        <Button size="small" onClick={onRefresh} loading={isFetching}>
          Оновити
        </Button>
      }
    >
      {isLoading ? <Skeleton active paragraph={{ rows: 3 }} /> : null}

      {!isLoading && isError ? (
        <Alert type="error" showIcon message="Не вдалося прочитати стан інтеграції" />
      ) : null}

      {!isLoading && !isError && health ? (
        <Space direction="vertical" size="middle" className="w-full">
          <Alert
            type={alertType(health.circuitState)}
            showIcon
            message={
              <Space wrap>
                <StatusTag dictionary={CIRCUIT_STATE} value={health.circuitState} />
                {health.transport === 'stub' ? (
                  <Tag color="default">Тестовий транспорт</Tag>
                ) : (
                  <Tag color="blue">Робочий транспорт</Tag>
                )}
              </Space>
            }
            description={CIRCUIT_EXPLANATION[health.circuitState] ?? 'Стан невідомий.'}
          />

          <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }} bordered>
            <Descriptions.Item label="Невдач підряд">
              <span className="numeric">{formatCount(health.consecutiveFailures)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="Остання помилка">
              <DateValue value={health.lastErrorAt} withTime />
            </Descriptions.Item>
            <Descriptions.Item label="Розімкнено о">
              <DateValue value={health.openedAt} withTime />
            </Descriptions.Item>
            <Descriptions.Item label="Оновлення">
              <Typography.Text type="secondary">кожні 15 с</Typography.Text>
            </Descriptions.Item>
          </Descriptions>

          {health.transport === 'stub' ? (
            <Typography.Text type="secondary">
              Застосунок працює з тестовим транспортом: розрахунки й відправлення несправжні та
              нікуди не надсилаються.
            </Typography.Text>
          ) : null}
        </Space>
      ) : null}
    </Card>
  );
}
