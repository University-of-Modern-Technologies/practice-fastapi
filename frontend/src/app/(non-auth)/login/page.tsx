'use client';

import { Alert, Button, Card, Form, Input, Typography } from 'antd';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect } from 'react';
import { ApiError } from '@/shared/api';
import { useLogin } from '@/shared/auth';
import { useAuthStore } from '@/shared/stores';
import { Brand } from '@/templates/layouts';
import { loginSchema, type LoginFormValues } from './login.validation';

/** Only same-origin paths are honoured, so the parameter cannot bounce the user off-site. */
const safeNext = (value: string | null): string =>
  value && value.startsWith('/') && !value.startsWith('//') ? value : '/';

const describe = (error: unknown): string => {
  if (error instanceof ApiError && error.status === 401) return 'Невірна пошта або пароль';
  if (error instanceof ApiError && error.status === 0) return 'Немає зв’язку із сервером';
  return 'Не вдалося увійти. Спробуйте ще раз';
};

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const status = useAuthStore((state) => state.status);
  const login = useLogin();
  const next = safeNext(searchParams.get('next'));

  useEffect(() => {
    // Covers both a successful sign-in and arriving here with a live session.
    if (status === 'authenticated') router.replace(next);
  }, [status, next, router]);

  const onFinish = (values: LoginFormValues) => {
    login.mutate(values);
  };

  return (
    <Card
      className="shadow-[0_12px_40px_-12px_rgba(15,23,42,0.18)]"
      style={{ width: '100%', maxWidth: 400 }}
      styles={{ body: { padding: 32 } }}
    >
      <div className="mb-6 flex flex-col items-center text-center">
        <div className="mb-5">
          <Brand />
        </div>
        <Typography.Title level={1} style={{ margin: '0 0 4px', fontSize: 22, fontWeight: 600 }}>
          Вхід
        </Typography.Title>
        <Typography.Text type="secondary">Увійдіть, щоб продовжити роботу</Typography.Text>
      </div>

      {login.isError ? (
        <Alert type="error" showIcon className="mb-4" message={describe(login.error)} />
      ) : null}

      <Form<LoginFormValues> layout="vertical" onFinish={onFinish} requiredMark={false}>
        <Form.Item
          name="email"
          label="Пошта"
          rules={[
            {
              validator: (_rule, value: string) => {
                const result = loginSchema.shape.email.safeParse(value);
                return result.success
                  ? Promise.resolve()
                  : Promise.reject(new Error(result.error.issues[0]?.message));
              },
            },
          ]}
        >
          <Input autoComplete="email" autoFocus placeholder="user@example.com" size="large" />
        </Form.Item>

        <Form.Item
          name="password"
          label="Пароль"
          rules={[
            {
              validator: (_rule, value: string) => {
                const result = loginSchema.shape.password.safeParse(value);
                return result.success
                  ? Promise.resolve()
                  : Promise.reject(new Error(result.error.issues[0]?.message));
              },
            },
          ]}
        >
          <Input.Password autoComplete="current-password" size="large" />
        </Form.Item>

        <Button type="primary" htmlType="submit" size="large" block loading={login.isPending}>
          Увійти
        </Button>
      </Form>
    </Card>
  );
}

export default function LoginPage() {
  // useSearchParams suspends during prerendering, so the boundary is required.
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
