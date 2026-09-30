/**
 * The single source of the palette. Ant Design reads it through ConfigProvider
 * and emits it as --crm-* CSS variables; the Tailwind colours in globals.css
 * point at those variables, so a utility class and a component can never drift
 * to different shades of the same colour.
 */
export const PALETTE = {
  primary: '#4F46E5',
  success: '#16A34A',
  warning: '#D97706',
  danger: '#DC2626',
  info: '#0EA5E9',
} as const;

export const SURFACE = {
  light: { background: '#F7F7FB', container: '#FFFFFF', border: '#E6E6EF', text: '#0F172A' },
  dark: { background: '#16161D', container: '#1E1E27', border: '#2C2C38', text: '#F1F5F9' },
} as const;

export const RADIUS = 8;

export const FONT_FAMILY =
  "'Inter Variable', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

export const FONT_FAMILY_MONO = "'JetBrains Mono Variable', ui-monospace, monospace";
