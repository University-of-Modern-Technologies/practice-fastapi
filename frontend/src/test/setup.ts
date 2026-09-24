import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

/**
 * jsdom implements neither of these, and antd reaches for both: the responsive
 * observers behind Table and Select call `ResizeObserver`, and the theme
 * algorithm reads `matchMedia`. Without the stubs a component test fails on the
 * environment rather than on the component.
 */
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

/**
 * jsdom refuses the two-argument form and prints a "Not implemented" stack for
 * it. antd measures the scrollbar that way on every table render, so without
 * this the noise buries whatever a failing test is actually saying.
 */
if (typeof window !== 'undefined') {
  const computedStyle = window.getComputedStyle.bind(window);
  window.getComputedStyle = ((element: Element) =>
    computedStyle(element)) as typeof window.getComputedStyle;
}

// Unmounting between tests keeps a component's timers and subscriptions from
// outliving the case that created them.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
