'use client';

import { Alert, Card, Col, Row, Skeleton, Statistic } from 'antd';
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { EmptyState, MoneyValue } from '@/components';
// The build reports the window's totals without naming a currency: every
// statement it knows is in one, and a figure that summed several would be
// wrong whatever label it carried. The default is what the rest of the client
// formats an unlabelled amount with.
import { DEFAULT_CURRENCY, Money } from '@/lib/money';
import { formatCount } from '@/lib/number';
import { PALETTE, statusMeta, type StatusColor } from '@/shared/constants';
import { PAYMENT_MATCH_STATUS, type FinanceSummary } from '../finance.types';

/**
 * Axis furniture follows the theme through Ant Design's variables, so the chart
 * stays readable on the dark background without a second palette.
 *
 * These four helpers are a copy of what `analytics/_components/report-card`
 * already holds. They are duplicated rather than imported because that file
 * belongs to another section, and reaching into it would be the boundary
 * crossing the course names out loud — the right fix is to lift them into the
 * shared layer, which is not this module's to do.
 */
const CHART_TEXT_COLOR = 'var(--crm-color-text-secondary)';
const CHART_GRID_COLOR = 'var(--crm-color-split)';
const CHART_HEIGHT = 260;

const statusChartColor = (color: StatusColor): string =>
  ({
    default: PALETTE.info,
    processing: PALETTE.primary,
    success: PALETTE.success,
    warning: PALETTE.warning,
    error: PALETTE.danger,
  })[color];

interface FinanceSummaryCardProps {
  readonly summary: FinanceSummary | undefined;
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly extra?: React.ReactNode;
}

/**
 * The period read as one picture.
 *
 * The chart shows composition and not a trend, which is a decision the contract
 * made rather than a preference: the summary is specified as inflow, outflow
 * and the shares each match state holds, and none of those has a time axis. A
 * line over days would be drawn from data the endpoint is not described as
 * returning, and would be the first thing to disagree with the server.
 *
 * What the bars do carry is the thing the section is for: how much of the money
 * that came through the account has been tied to an order and how much has not.
 * A tall `UNMATCHED` bar is information, not an alarm — which is why it is
 * painted in the same neutral colour as its tag and not in red.
 */
export function FinanceSummaryCard({
  summary,
  isLoading,
  isError,
  extra,
}: FinanceSummaryCardProps) {
  const shares = summary?.statuses ?? [];

  const data = shares.map((share) => {
    const meta = statusMeta(PAYMENT_MATCH_STATUS, share.status);
    return {
      label: meta.label,
      count: share.count,
      amount: share.amount,
      color: statusChartColor(meta.color),
    };
  });

  const body = (): React.ReactNode => {
    if (isLoading) return <Skeleton active paragraph={{ rows: 6 }} />;
    if (isError) return <Alert type="error" showIcon message="Не вдалося прочитати підсумок" />;
    if (summary === undefined) return <EmptyState description="За обраний період даних немає" />;

    return (
      <>
        <Row gutter={[16, 8]} className="mb-4">
          <Col xs={24} sm={6}>
            <Statistic
              title="Надходження"
              valueRender={() => (
                <MoneyValue value={summary.inflow} currency={DEFAULT_CURRENCY} showCurrency />
              )}
            />
          </Col>
          <Col xs={24} sm={6}>
            <Statistic
              title="Списання"
              valueRender={() => (
                <MoneyValue value={summary.outflow} currency={DEFAULT_CURRENCY} showCurrency />
              )}
            />
          </Col>
          <Col xs={24} sm={6}>
            <Statistic
              title="Різниця"
              valueRender={() => (
                <MoneyValue value={summary.net} currency={DEFAULT_CURRENCY} showCurrency />
              )}
            />
          </Col>
          <Col xs={24} sm={6}>
            <Statistic title="Транзакцій" value={summary.transactionCount} />
          </Col>
        </Row>

        {data.length === 0 ? (
          <EmptyState description="За обраний період транзакцій немає" />
        ) : (
          <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke={CHART_GRID_COLOR} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: CHART_TEXT_COLOR, fontSize: 12 }} />
              <YAxis allowDecimals={false} tick={{ fill: CHART_TEXT_COLOR, fontSize: 12 }} />
              <Tooltip
                formatter={(value: unknown, _name: unknown, item: unknown) => {
                  // The count is what the bar is tall by; the amount is what it
                  // is about, and it is formatted through `Money` like every
                  // other sum in the client.
                  const amount = (item as { payload?: { amount?: string } }).payload?.amount;
                  const money =
                    amount === undefined
                      ? ''
                      : ` · ${Money.parseOrZero(amount, DEFAULT_CURRENCY).format()}`;
                  return `${formatCount(Number(value))}${money}`;
                }}
              />
              <Bar dataKey="count" name="Транзакцій" radius={[4, 4, 0, 0]}>
                {data.map((row) => (
                  <Cell key={row.label} fill={row.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </>
    );
  };

  return (
    <Card
      size="small"
      title="Підсумок за період"
      className="mb-4"
      {...(extra ? { extra } : {})}
      styles={{ body: { minHeight: 260 } }}
    >
      {body()}
    </Card>
  );
}
