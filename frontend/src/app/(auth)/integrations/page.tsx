'use client';

import { Col, Row } from 'antd';
import { useCallback, useState } from 'react';
import { ModuleUnavailable, PageHeader, PermissionGate } from '@/components';
import { HealthCard, QuoteForm, ShipmentForm, ShipmentLookup } from './_components';
import { useDeliveryHealth } from './integrations.queries';
import { isModuleUnavailable } from './integrations.service';
import type { QuoteResult } from './integrations.types';

export default function IntegrationsPage() {
  const health = useDeliveryHealth();
  const [quote, setQuote] = useState<QuoteResult | null>(null);
  const [reportedMissing, setReportedMissing] = useState(false);

  // Any of the three calls may be the first to reveal that this API build does
  // not serve the integration; the section is described once, not per card.
  const unavailable = isModuleUnavailable(health.error) || reportedMissing;
  const onUnavailable = useCallback(() => setReportedMissing(true), []);

  return (
    <PermissionGate resource="integrations" action="read">
      <PageHeader
        title="Інтеграції"
        description="Служба доставки: стан зʼєднання, розрахунок вартості та відправлення"
      />

      {unavailable ? (
        <ModuleUnavailable
          missing="інтеграцію з доставкою"
          requirement="розрахунок і відправлення потрібні"
        />
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={24}>
            <HealthCard
              health={health.data}
              isLoading={health.isPending}
              isError={health.isError}
              isFetching={health.isFetching}
              onRefresh={() => void health.refetch()}
            />
          </Col>

          <Col xs={24} xl={12}>
            <QuoteForm onQuoted={setQuote} onUnavailable={onUnavailable} />
          </Col>

          <Col xs={24} xl={12}>
            <ShipmentForm quote={quote} onUnavailable={onUnavailable} />
          </Col>

          <Col xs={24}>
            <ShipmentLookup onUnavailable={onUnavailable} />
          </Col>
        </Row>
      )}
    </PermissionGate>
  );
}
