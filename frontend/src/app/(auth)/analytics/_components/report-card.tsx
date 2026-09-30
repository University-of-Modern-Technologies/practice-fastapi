'use client';

import { Alert, Button, Card, Skeleton } from 'antd';
import { Download } from 'lucide-react';
import type { ReactNode } from 'react';
import { EmptyState } from '@/components';
import { Money } from '@/lib/money';
import { PALETTE, type StatusColor } from '@/shared/constants';
import type { MoneyWire } from '@/types/domain';

/** Says the period holds nothing, rather than drawing an axis with no marks on it. */
export const EMPTY_REPORT_TEXT = 'За обраний період даних немає';

/** Series colours. Taken from the palette so a chart cannot drift from the theme. */
export const CHART_COLORS = {
  primary: PALETTE.primary,
  success: PALETTE.success,
  warning: PALETTE.warning,
  danger: PALETTE.danger,
  info: PALETTE.info,
} as const;

/**
 * Axis furniture follows the theme through Ant Design's variables, so the same
 * chart stays readable on the dark background without a second palette.
 */
export const CHART_TEXT_COLOR = 'var(--crm-color-text-secondary)';
export const CHART_GRID_COLOR = 'var(--crm-color-split)';

/**
 * A chart needs a coordinate, and a coordinate is a number. The conversion
 * happens once, here, and only for plotting: every amount the user reads is
 * formatted from the wire string through `Money`, never from this number.
 */
export const chartAmount = (value: MoneyWire): number => Number(Money.parseOrZero(value).toWire());

/** Formats an amount for a label, a tick, or a tooltip — the only money formatter used. */
export const formatAmount = (value: MoneyWire | number): string =>
  Money.parseOrZero(typeof value === 'number' ? value.toFixed(2) : value).format();

/**
 * A bar has to be painted, and the enum registry describes a state by an Ant
 * Design preset name rather than by a colour. Translating it here keeps the
 * charts on the same five colours the tags use.
 */
export const statusChartColor = (color: StatusColor): string =>
  ({
    default: PALETTE.info,
    processing: PALETTE.primary,
    success: PALETTE.success,
    warning: PALETTE.warning,
    error: PALETTE.danger,
  })[color];

interface ExportButtonProps {
  readonly onExport: () => void;
  readonly isExporting: boolean;
}

/**
 * The same control on every card, so a report the user is looking at can
 * always be exported without hunting for a differently placed action on the
 * next one.
 */
export function ExportButton({ onExport, isExporting }: ExportButtonProps) {
  return (
    <Button size="small" icon={<Download size={14} />} loading={isExporting} onClick={onExport}>
      CSV
    </Button>
  );
}

interface ReportCardProps {
  readonly title: string;
  readonly description?: string;
  /** Controls that belong to this report alone — a period switch, a limit. */
  readonly extra?: ReactNode;
  readonly isLoading: boolean;
  readonly isError: boolean;
  /** True when the report answered with nothing for the chosen window. */
  readonly isEmpty: boolean;
  readonly children: ReactNode;
}

/**
 * The frame every report shares: one place decides what "still loading",
 * "failed" and "nothing here" look like, so five cards cannot answer the same
 * question in five different ways.
 */
export function ReportCard({
  title,
  description,
  extra,
  isLoading,
  isError,
  isEmpty,
  children,
}: ReportCardProps) {
  const body = (): ReactNode => {
    if (isLoading) return <Skeleton active paragraph={{ rows: 6 }} />;
    if (isError) {
      return <Alert type="error" showIcon message="Не вдалося побудувати звіт" />;
    }
    if (isEmpty) return <EmptyState description={EMPTY_REPORT_TEXT} />;
    return children;
  };

  return (
    <Card
      size="small"
      title={title}
      {...(extra ? { extra } : {})}
      styles={{ body: { minHeight: 260 } }}
    >
      {description ? (
        <p className="mb-3 text-sm" style={{ color: CHART_TEXT_COLOR }}>
          {description}
        </p>
      ) : null}
      {body()}
    </Card>
  );
}
