'use client';

import { Button, Result, Space } from 'antd';
import { StatusScreen } from '@/components/status-screen';
import { Brand } from '@/templates/layouts';

/**
 * Catches what a query or a render did not. The user gets a way forward rather
 * than a blank page, and the digest identifies the failure in the server logs.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <StatusScreen brand={<Brand />}>
      <Result
        status="500"
        title="Щось пішло не так"
        subTitle={error.digest ? `Код помилки: ${error.digest}` : error.message}
        extra={
          <Space wrap className="justify-center">
            <Button type="primary" onClick={reset}>
              Спробувати ще раз
            </Button>
            <Button href="/">На головну</Button>
          </Space>
        }
      />
    </StatusScreen>
  );
}
