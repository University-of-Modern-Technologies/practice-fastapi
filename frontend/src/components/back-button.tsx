'use client';

import { Button } from 'antd';
import { ArrowLeft } from 'lucide-react';
import { useRouter } from 'next/navigation';

interface BackButtonProps {
  /** Where to go when there is no history to step back through. */
  readonly href?: string;
  /** Renders as "Скасувати" — for a form the user may be abandoning. */
  readonly cancel?: boolean;
}

export function BackButton({ href, cancel = false }: BackButtonProps) {
  const router = useRouter();

  return (
    <Button
      {...(cancel ? {} : { icon: <ArrowLeft size={16} /> })}
      onClick={() => (href ? router.push(href) : router.back())}
    >
      {cancel ? 'Скасувати' : 'Назад'}
    </Button>
  );
}
