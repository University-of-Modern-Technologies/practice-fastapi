'use client';

import { Result, Typography } from 'antd';

interface ModuleUnavailableProps {
  /** What this API build does not serve, in the accusative: `звіти аналітики`. */
  readonly missing: string;
  /** Tail of the closing sentence: `аналітика потрібна`. */
  readonly requirement: string;
}

/**
 * Some sections are served by one API build and not by another, and the client
 * is never told which one it is talking to. A missing section is therefore an
 * expected answer: it is explained here instead of being reported as a failure,
 * and the menu entry stays where it is so nothing else on the page shifts.
 *
 * Only the two module-specific fragments are passed in — the frame and the
 * reassurance are worded once, so three sections cannot explain the same
 * situation in three different ways.
 */
export function ModuleUnavailable({ missing, requirement }: ModuleUnavailableProps) {
  return (
    <Result
      status="info"
      title="Розділ недоступний у поточній збірці API"
      subTitle={
        <Typography.Text type="secondary">
          {`Сервер, до якого підключено застосунок, не надає ${missing}. Решта розділів працює як звичайно — зверніться до адміністратора, якщо ${requirement}.`}
        </Typography.Text>
      }
    />
  );
}
