import { Typography } from 'antd';
import type { ReactNode } from 'react';

interface PageHeaderProps {
  readonly title: string;
  readonly description?: string;
  /** Primary actions for the page, aligned to the trailing edge. */
  readonly actions?: ReactNode;
}

/**
 * The top of every page. The title is the page's only first-level heading;
 * its size is set here rather than by the level, so every page reads the same.
 * On a narrow screen the actions drop below the title instead of squeezing it.
 */
export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <Typography.Title
          level={1}
          className="break-words"
          style={{ margin: 0, fontSize: 22, lineHeight: 1.35, fontWeight: 600 }}
        >
          {title}
        </Typography.Title>
        {description ? (
          <Typography.Text type="secondary" className="mt-1 block">
            {description}
          </Typography.Text>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
