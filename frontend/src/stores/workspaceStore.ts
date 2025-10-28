import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

interface ActiveChallenge {
  dojoId: string;
  moduleId: string;
  challengeId: string;
  challengeName: string;
  dojoName: string;
  moduleName: string;
  isStarting?: boolean;
}

interface WorkspaceStore {
  // Sidebar state
  sidebarCollapsed: boolean;
  sidebarWidth: number;
  isResizing: boolean;

  // Workspace view state
  isFullScreen: boolean;
  headerHidden: boolean;
  isMinimized: boolean;

  // Service state
  activeService: string;
  preferredService: string;

  // UI state
  commandPaletteOpen: boolean;

  // Active challenge/resource state
  activeChallenge: ActiveChallenge | null;
  activeResource: string | null;

  // Actions - Sidebar
  setSidebarCollapsed: (collapsed: boolean) => void;
  setSidebarWidth: (width: number) => void;
  setIsResizing: (isResizing: boolean) => void;

  // Actions - Workspace view
  setFullScreen: (fullScreen: boolean) => void;
  setHeaderHidden: (hidden: boolean) => void;
  setMinimized: (minimized: boolean) => void;

  // Actions - Service
  setActiveService: (service: string) => void;

  // Actions - UI
  setCommandPaletteOpen: (open: boolean) => void;

  // Actions - Active challenge/resource
  setActiveChallenge: (challenge: ActiveChallenge | null) => void;
  setActiveResource: (resourceId: string | null) => void;

  // Actions - Reset
  resetWorkspace: () => void;
  closeWorkspace: () => void;
}

// Load preferred service from localStorage
const getPreferredService = (): string => {
  try {
    return localStorage.getItem("dojo-preferred-service") || "terminal";
  } catch {
    return "terminal";
  }
};

const defaultWorkspaceState = {
  sidebarCollapsed: false,
  sidebarWidth: 380,
  isFullScreen: false,
  headerHidden: false,
  isMinimized: false,
  activeService: getPreferredService(),
  preferredService: getPreferredService(),
  commandPaletteOpen: false,
  activeChallenge: null,
  activeResource: null,
  isResizing: false,
};

export const useWorkspaceStore = create<WorkspaceStore>()(
  subscribeWithSelector((set, get) => ({
    // Initial state
    ...defaultWorkspaceState,

    // Actions - Sidebar
    setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

    setSidebarWidth: (width) => set({ sidebarWidth: width }),

    // Actions - Workspace view
    setFullScreen: (fullScreen) => set({ isFullScreen: fullScreen }),

    setHeaderHidden: (hidden) => set({ headerHidden: hidden }),

    setMinimized: (minimized) => set({ isMinimized: minimized }),

    // Actions - Service
    setActiveService: (service) => {
      // Save preference to localStorage
      try {
        localStorage.setItem("dojo-preferred-service", service);
      } catch (error) {
        console.warn("Failed to save service preference:", error);
      }

      set({
        activeService: service,
        preferredService: service,
      });
    },

    // Actions - UI
    setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),

    // Actions - Active challenge/resource
    setActiveChallenge: (challenge) => set({ activeChallenge: challenge }),

    setActiveResource: (resourceId) => set({ activeResource: resourceId }),

    setIsResizing: (isResizing) => set({ isResizing }),

    // Actions - Reset
    resetWorkspace: () => set(defaultWorkspaceState),

    // Close workspace (clears active challenge/resource but keeps state)
    closeWorkspace: () => set({
      activeChallenge: null,
      activeResource: null,
      isMinimized: false,
    }),
  })),
);

// Selectors for common use cases
export const useWorkspaceSidebar = () => {
  const sidebarCollapsed = useWorkspaceStore((state) => state.sidebarCollapsed);
  const sidebarWidth = useWorkspaceStore((state) => state.sidebarWidth);
  const setSidebarCollapsed = useWorkspaceStore(
    (state) => state.setSidebarCollapsed,
  );
  const setSidebarWidth = useWorkspaceStore((state) => state.setSidebarWidth);

  return {
    sidebarCollapsed,
    sidebarWidth,
    setSidebarCollapsed,
    setSidebarWidth,
  };
};

export const useWorkspaceService = () => {
  const activeService = useWorkspaceStore((state) => state.activeService);
  const preferredService = useWorkspaceStore((state) => state.preferredService);
  const setActiveService = useWorkspaceStore((state) => state.setActiveService);

  return {
    activeService,
    preferredService,
    setActiveService,
  };
};

export const useWorkspaceView = () => {
  const isFullScreen = useWorkspaceStore((state) => state.isFullScreen);
  const headerHidden = useWorkspaceStore((state) => state.headerHidden);
  const isMinimized = useWorkspaceStore((state) => state.isMinimized);
  const setFullScreen = useWorkspaceStore((state) => state.setFullScreen);
  const setHeaderHidden = useWorkspaceStore((state) => state.setHeaderHidden);
  const setMinimized = useWorkspaceStore((state) => state.setMinimized);

  return {
    isFullScreen,
    headerHidden,
    isMinimized,
    setFullScreen,
    setHeaderHidden,
    setMinimized,
  };
};

export const useWorkspaceChallenge = () => {
  const activeChallenge = useWorkspaceStore((state) => state.activeChallenge);
  const setActiveChallenge = useWorkspaceStore(
    (state) => state.setActiveChallenge,
  );

  return {
    activeChallenge,
    setActiveChallenge,
  };
};

export const useWorkspaceResource = () => {
  const activeResource = useWorkspaceStore((state) => state.activeResource);
  const setActiveResource = useWorkspaceStore(
    (state) => state.setActiveResource,
  );

  return {
    activeResource,
    setActiveResource,
  };
};
