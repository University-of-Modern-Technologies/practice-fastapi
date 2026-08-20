'use client';

import { Col, Row } from 'antd';
import { useState } from 'react';
import { ModuleUnavailable, PageHeader, PermissionGate } from '@/components';
import { DealSummaryPanel, InquiryClassifierPanel } from './_components';

export default function AiPage() {
  /**
   * Both assistant routes are POST, so the page cannot ask in advance whether
   * this API build serves them: it learns from the first attempt a user makes.
   * Once either panel meets a 404 or a dead transport, the whole section is
   * known to be absent and stays that way until the page is reloaded — a second
   * attempt would only repeat the same wait for the same answer.
   */
  const [unavailable, setUnavailable] = useState(false);
  const markUnavailable = (): void => setUnavailable(true);

  return (
    <PermissionGate resource="ai" action="use">
      <PageHeader
        title="AI-помічник"
        description="Резюме угоди та класифікація звернення. Відповіді моделі — підказка, а не рішення."
      />

      {unavailable ? (
        <ModuleUnavailable missing="AI-помічника" requirement="помічник потрібен" />
      ) : (
        // Two independent panels: each sends its own request, and a failure in
        // one leaves the other usable.
        <Row gutter={[16, 16]}>
          <Col xs={24} xl={12}>
            <DealSummaryPanel onUnavailable={markUnavailable} />
          </Col>
          <Col xs={24} xl={12}>
            <InquiryClassifierPanel onUnavailable={markUnavailable} />
          </Col>
        </Row>
      )}
    </PermissionGate>
  );
}
