import { Button, Result } from 'antd';
import Link from 'next/link';

export default function NotFound() {
  return (
    <Result
      status="404"
      title="Сторінку не знайдено"
      subTitle="Схоже, такої адреси не існує."
      extra={
        <Link href="/">
          <Button type="primary">На головну</Button>
        </Link>
      }
    />
  );
}
