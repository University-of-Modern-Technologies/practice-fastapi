import { Button, Result } from 'antd';
import { StatusScreen } from '@/components/status-screen';
import { Brand } from '@/templates/layouts';

export default function NotFound() {
  return (
    <StatusScreen brand={<Brand />}>
      <Result
        status="404"
        title="Сторінку не знайдено"
        subTitle="Схоже, такої адреси не існує."
        extra={
          // A button that is itself the link: a <button> inside an <a> is
          // invalid markup and announces the control twice.
          <Button type="primary" href="/">
            На головну
          </Button>
        }
      />
    </StatusScreen>
  );
}
