import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

interface UiState {
  /** The desktop sidebar shows icons only. Remembered between visits. */
  readonly sidebarCollapsed: boolean;
  /** The navigation drawer on a narrow screen. Never remembered. */
  readonly mobileNavOpen: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setMobileNavOpen: (open: boolean) => void;
}

/**
 * Hydration is skipped on purpose: the server renders the sidebar expanded,
 * and reading the stored choice before React has hydrated would give the
 * client a different first render. The shell calls `persist.rehydrate()` once
 * it has mounted.
 */
export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      mobileNavOpen: false,
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
      setMobileNavOpen: (mobileNavOpen) => set({ mobileNavOpen }),
    }),
    {
      name: 'crm-ui',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ sidebarCollapsed: state.sidebarCollapsed }),
      skipHydration: true,
    },
  ),
);
