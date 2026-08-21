'use client';

import { Col, Form, Input, InputNumber, Row, Typography } from 'antd';
import { zodRule } from '@/components';
import {
  PARCEL_LIMITS,
  citySchema,
  countrySchema,
  line1Schema,
  normalizeCountry,
  postalCodeSchema,
} from '../integrations.validation';

interface AddressFieldsProps {
  /** Path to the address inside the form values — `['origin']`, `['destination']`. */
  readonly name: string;
  readonly legend: string;
  readonly hint?: string;
}

/**
 * One definition of an address for both forms. The quote and the shipment must
 * describe the same place under the same rules, so a second copy of these four
 * fields would be a second chance for the two to disagree.
 */
export function AddressFields({ name, legend, hint }: AddressFieldsProps) {
  return (
    <>
      <Typography.Text strong className="mb-2 block">
        {legend}
      </Typography.Text>
      {hint ? (
        <Typography.Text type="secondary" className="mb-2 block">
          {hint}
        </Typography.Text>
      ) : null}

      <Row gutter={16}>
        <Col xs={12} md={6}>
          <Form.Item
            name={[name, 'country']}
            label="Країна"
            rules={[zodRule(countrySchema)]}
            // Only letters, upper case: the field shows exactly what is sent.
            normalize={normalizeCountry}
          >
            <Input placeholder="UA" maxLength={2} autoComplete="country" />
          </Form.Item>
        </Col>

        <Col xs={12} md={6}>
          <Form.Item name={[name, 'postalCode']} label="Індекс" rules={[zodRule(postalCodeSchema)]}>
            <Input placeholder="01001" maxLength={20} autoComplete="postal-code" />
          </Form.Item>
        </Col>

        <Col xs={24} md={12}>
          <Form.Item name={[name, 'city']} label="Місто" rules={[zodRule(citySchema)]}>
            <Input placeholder="Київ" maxLength={120} autoComplete="address-level2" />
          </Form.Item>
        </Col>
      </Row>

      <Form.Item name={[name, 'line1']} label="Адреса" rules={[zodRule(line1Schema)]}>
        <Input placeholder="вул. Хрещатик, 1, кв. 2" maxLength={200} autoComplete="address-line1" />
      </Form.Item>
    </>
  );
}

interface ParcelFieldsProps {
  /** Path to the parcel inside the form values; both forms use `'parcel'`. */
  readonly name: string;
}

/**
 * Kept beside the address for the same reason: the shipment is created for the
 * parcel the price was calculated for, so both forms measure it by one set of
 * bounds. The limits come from the contract rather than from the markup, so the
 * field cannot offer a value the API refuses.
 */
export function ParcelFields({ name }: ParcelFieldsProps) {
  const { weightGrams, dimensionCm } = PARCEL_LIMITS;

  return (
    <>
      <Typography.Text strong className="mb-2 block">
        Габарити відправлення
      </Typography.Text>

      <Row gutter={16}>
        <Col xs={12} md={6}>
          <Form.Item
            name={[name, 'weightGrams']}
            label="Вага, г"
            rules={[{ required: true, message: 'Вкажіть вагу' }]}
          >
            <InputNumber
              className="numeric w-full"
              min={weightGrams.min}
              max={weightGrams.max}
              step={100}
              precision={0}
              addonAfter="г"
            />
          </Form.Item>
        </Col>

        <Col xs={12} md={6}>
          <Form.Item
            name={[name, 'lengthCm']}
            label="Довжина, см"
            rules={[{ required: true, message: 'Вкажіть довжину' }]}
          >
            <InputNumber
              className="numeric w-full"
              min={dimensionCm.min}
              max={dimensionCm.max}
              precision={0}
              addonAfter="см"
            />
          </Form.Item>
        </Col>

        <Col xs={12} md={6}>
          <Form.Item
            name={[name, 'widthCm']}
            label="Ширина, см"
            rules={[{ required: true, message: 'Вкажіть ширину' }]}
          >
            <InputNumber
              className="numeric w-full"
              min={dimensionCm.min}
              max={dimensionCm.max}
              precision={0}
              addonAfter="см"
            />
          </Form.Item>
        </Col>

        <Col xs={12} md={6}>
          <Form.Item
            name={[name, 'heightCm']}
            label="Висота, см"
            rules={[{ required: true, message: 'Вкажіть висоту' }]}
          >
            <InputNumber
              className="numeric w-full"
              min={dimensionCm.min}
              max={dimensionCm.max}
              precision={0}
              addonAfter="см"
            />
          </Form.Item>
        </Col>
      </Row>
    </>
  );
}
