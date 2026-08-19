import type { Rule } from 'antd/es/form';
import type { ZodType } from 'zod';

/**
 * Turns a Zod schema into an Ant Design rule, so a field is described once and
 * the same definition guards both the form and whatever the module sends to the
 * API. Without this, every field carries two descriptions that drift apart.
 */
export const zodRule = (schema: ZodType): Rule => ({
  validator: (_rule, value: unknown) => {
    const result = schema.safeParse(value);
    if (result.success) return Promise.resolve();
    const [issue] = result.error.issues;
    return Promise.reject(new Error(issue?.message ?? 'Некоректне значення'));
  },
});

/** Marks a field as required with the wording used across the application. */
export const requiredRule = (message = 'Обовʼязкове поле'): Rule => ({
  required: true,
  message,
});
