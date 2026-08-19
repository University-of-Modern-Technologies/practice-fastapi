'use client';

import { Alert, Card, Input, Skeleton, Space } from 'antd';
import { useEffect, useState } from 'react';
import {
  CopyableValue,
  DateValue,
  DetailsCard,
  DetailsItem,
  EmptyState,
  StatusTag,
} from '@/components';
import { SHIPMENT_STATUS } from '@/shared/constants';
import { useShipment } from '../integrations.queries';
import { isModuleUnavailable, isShipmentMissing } from '../integrations.service';
import type { Shipment } from '../integrations.types';

interface ShipmentDetailsProps {
  readonly shipment: Shipment;
}

/** The one description of a shipment: the lookup and the create form show it alike. */
export function ShipmentDetails({ shipment }: ShipmentDetailsProps) {
  return (
    <DetailsCard>
      <DetailsItem label="Стан">
        <StatusTag dictionary={SHIPMENT_STATUS} value={shipment.status} />
      </DetailsItem>
      <DetailsItem label="Перевізник">{shipment.carrier}</DetailsItem>
      <DetailsItem label="Номер відправлення">
        <CopyableValue value={shipment.shipmentId} />
      </DetailsItem>
      <DetailsItem label="Замовлення">
        <CopyableValue value={shipment.orderId} />
      </DetailsItem>
      <DetailsItem label="Трек-номер">
        <CopyableValue value={shipment.trackingNumber} />
      </DetailsItem>
      <DetailsItem label="Створено">
        <DateValue value={shipment.createdAt} withTime />
      </DetailsItem>
      <DetailsItem label="Очікувана доставка">
        <DateValue value={shipment.estimatedDeliveryAt} withTime />
      </DetailsItem>
    </DetailsCard>
  );
}

interface ShipmentLookupProps {
  readonly onUnavailable: () => void;
}

export function ShipmentLookup({ onUnavailable }: ShipmentLookupProps) {
  const [id, setId] = useState('');
  const shipment = useShipment(id);

  // The search is where a build without the integration is met most often, so
  // the whole page is switched over rather than this one card reporting a 404.
  useEffect(() => {
    if (isModuleUnavailable(shipment.error)) onUnavailable();
  }, [onUnavailable, shipment.error]);

  const missing = isShipmentMissing(shipment.error);
  const failed = shipment.isError && !missing && !isModuleUnavailable(shipment.error);

  return (
    <Card size="small" title="Пошук відправлення">
      <Space direction="vertical" size="middle" className="w-full">
        <Input.Search
          placeholder="Номер відправлення"
          enterButton="Знайти"
          allowClear
          maxLength={128}
          loading={shipment.isFetching}
          // Committed on Enter or on the button: a partial identifier typed
          // character by character would fire a request per keystroke.
          onSearch={(value) => setId(value.trim())}
        />

        {id === '' ? (
          <EmptyState description="Введіть номер відправлення, щоб побачити його стан" />
        ) : null}

        {id !== '' && shipment.isPending ? <Skeleton active paragraph={{ rows: 3 }} /> : null}

        {missing ? (
          <Alert
            type="info"
            showIcon
            message="Відправлення не знайдено"
            description="Служба доставки не має запису з таким номером. Перевірте номер і спробуйте ще раз."
          />
        ) : null}

        {failed ? (
          <Alert type="error" showIcon message="Не вдалося прочитати стан відправлення" />
        ) : null}

        {shipment.data ? <ShipmentDetails shipment={shipment.data} /> : null}
      </Space>
    </Card>
  );
}
