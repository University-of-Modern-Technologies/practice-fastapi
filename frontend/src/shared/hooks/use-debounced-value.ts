'use client';

import { useEffect, useState } from 'react';

/**
 * Delays a value until it stops changing. Used for search boxes that query as
 * the user types: without it, "Alex" is four requests, and the three answers
 * for the prefixes are noise that may still arrive after the one that matters.
 */
export const useDebouncedValue = <T>(value: T, delayMs = 300): T => {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return settled;
};
