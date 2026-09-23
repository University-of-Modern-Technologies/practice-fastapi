'use client';

import { Alert, Button, Card, Space, Typography } from 'antd';
import { Download, Play } from 'lucide-react';
import { useEffect, useState } from 'react';
import { DateTime } from '@/lib/date-time';
import { useMutationFeedback } from '@/shared/hooks';
import { useCallRecording } from '../calls.queries';
import { isRecordingUnavailable } from '../calls.service';
import type { Call } from '../calls.types';

interface CallRecordingCardProps {
  readonly call: Call;
}

/** The longest delay `setTimeout` actually waits for; anything above fires immediately. */
const MAX_TIMER_MS = 2_147_483_647;

/**
 * The recording of the conversation, fetched on demand.
 *
 * The address the API hands back expires. That single fact decides the whole
 * shape of this card: the link is never stored with the record, never cached,
 * and never left on screen past `expiresAt` — a button that looks live and
 * fails when pressed is worse than one that says it has to be asked for again.
 * So the address is requested at the moment somebody wants to listen, it is
 * shown with the time it stops working, and when that time passes the link is
 * replaced by the offer to ask again.
 *
 * A call with no recording is not a failure either: the API answers 404 with
 * its own code, and that is a statement about this call, not about the module.
 */
export function CallRecordingCard({ call }: CallRecordingCardProps) {
  const { reportFailure } = useMutationFeedback();
  const recording = useCallRecording(call.id);

  const [isMissing, setIsMissing] = useState(false);
  const [isExpired, setIsExpired] = useState(false);

  const link = recording.data;

  /**
   * Milliseconds the address still has. Read outside render — the clock moves
   * on its own, and a value that changes between two renders of the same state
   * is not something a component may compute while rendering.
   */
  const remainingFor = (expiresAt: string): number => new Date(expiresAt).getTime() - Date.now();

  // The address dies on a schedule, so the card keeps that schedule rather
  // than waiting for the user to discover it by pressing a dead link.
  useEffect(() => {
    if (!link) return undefined;

    const remaining = remainingFor(link.expiresAt);
    // A delay past the 32-bit limit does not wait — it fires at once, which
    // would declare a long-lived address dead the moment it arrived. Beyond
    // that horizon no timer is set at all: nobody keeps this page open for
    // twenty-four days, and the expiry is re-read on the next request anyway.
    if (!Number.isFinite(remaining) || remaining <= 0 || remaining > MAX_TIMER_MS) return undefined;

    const timer = setTimeout(() => setIsExpired(true), remaining);
    return () => clearTimeout(timer);
  }, [link]);

  const request = (): void => {
    setIsMissing(false);

    recording.mutate(undefined, {
      onSuccess: (fresh) => {
        // A timestamp that cannot be read, or one already in the past, counts
        // as expired: a link whose lifetime is unknown is the one outcome with
        // no way back.
        setIsExpired(!(remainingFor(fresh.expiresAt) > 0));
      },
      onError: (error: unknown) => {
        // "This call has no recording" is an answer, not a breakage.
        if (isRecordingUnavailable(error)) {
          setIsMissing(true);
          return;
        }
        reportFailure(error);
      },
    });
  };

  const requestButton = (
    <Button
      icon={<Play size={16} />}
      loading={recording.isPending}
      onClick={request}
      // A fresh address is what the second press is for, so the button stays
      // enabled after the first one.
    >
      {link ? 'Оновити посилання' : 'Отримати запис'}
    </Button>
  );

  return (
    <Card title="Запис розмови" className="mb-4" extra={requestButton}>
      {call.recordingUrl === null && !link ? (
        <Typography.Paragraph type="secondary">
          За цим дзвінком запис не позначено. Перевірити все одно можна — адресу видає окремий
          запит.
        </Typography.Paragraph>
      ) : null}

      {isMissing ? (
        <Alert
          type="info"
          showIcon
          message="Запису розмови немає"
          description="Провайдер не зберіг запис цього дзвінка. Це не помилка — решта картки читається як звичайно."
        />
      ) : null}

      {link && !isExpired ? (
        <Space direction="vertical" size="small">
          <a href={link.url} target="_blank" rel="noreferrer">
            <Space size="small">
              <Download size={16} />
              Відкрити запис
            </Space>
          </a>
          <Typography.Text type="secondary">
            {`Посилання дійсне до ${DateTime.toDateTime(link.expiresAt)}`}
          </Typography.Text>
        </Space>
      ) : null}

      {link && isExpired ? (
        <Alert
          type="warning"
          showIcon
          message="Посилання на запис уже недійсне"
          description="Адреса видається на короткий час. Натисніть «Оновити посилання», щоб отримати нову."
        />
      ) : null}
    </Card>
  );
}
