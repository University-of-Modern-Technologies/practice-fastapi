'use client';

import { useEffect } from 'react';

/**
 * Warns before the browser discards a half-filled form. This covers only the
 * cases the browser owns — reload, tab close, back to another site. In-app
 * navigation is handled by the form itself, which knows what "dirty" means.
 */
export const useUnsavedChanges = (hasChanges: boolean): void => {
  useEffect(() => {
    if (!hasChanges) return;

    const warn = (event: BeforeUnloadEvent): void => {
      // The text is fixed by the browser; only cancelling the event matters.
      event.preventDefault();
      event.returnValue = '';
    };

    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [hasChanges]);
};
