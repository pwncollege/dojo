import { create } from 'zustand'

interface UIStore {
  // Header state
  isHeaderHidden: boolean

  // Animation settings
  animations: {
    fast: number      // 150ms - hover effects, micro-interactions
    medium: number    // 250ms - page transitions, content switching
    slow: number      // 400ms - modals, complex layout changes
    easing: string    // cubic-bezier for smooth transitions
  }

  // Workspace state
  workspaceState: {
    sidebarCollapsed: boolean
    sidebarWidth: number
    isFullScreen: boolean
    activeService: string
    preferredService: string
    commandPaletteOpen: boolean
    workspaceHeaderHidden: boolean
  }

  // Active challenge state
  activeChallenge: {
    dojoId: string
    moduleId: string
    challengeId: string
    challengeName: string
    dojoName: string
    moduleName: string
    isStarting?: boolean // Track if challenge is currently being started
  } | null

  // Actions - Header
  setHeaderHidden: (hidden: boolean) => void

  // Actions - Workspace
  setSidebarCollapsed: (collapsed: boolean) => void
  setSidebarWidth: (width: number) => void
  setFullScreen: (fullScreen: boolean) => void
  setActiveService: (service: string) => void
  setCommandPaletteOpen: (open: boolean) => void
  setWorkspaceHeaderHidden: (hidden: boolean) => void

  // Actions - Active Challenge
  setActiveChallenge: (challenge: UIStore['activeChallenge']) => void
  fetchActiveChallenge: () => Promise<void>
}

// Load preferred service from localStorage
const getPreferredService = (): string => {
  try {
    return localStorage.getItem('dojo-preferred-service') || 'terminal'
  } catch {
    return 'terminal'
  }
}

const defaultWorkspaceState = {
  sidebarCollapsed: false,
  sidebarWidth: 380,
  isFullScreen: false,
  activeService: getPreferredService(),
  preferredService: getPreferredService(),
  commandPaletteOpen: false,
  workspaceHeaderHidden: false
}

const defaultAnimations = {
  fast: 0.15,    // 150ms - hover effects, micro-interactions
  medium: 0.25,  // 250ms - page transitions, content switching
  slow: 0.4,     // 400ms - modals, complex layout changes
  easing: 'cubic-bezier(0.25, 0.46, 0.45, 0.94)' // Apple-grade easing
}

export const useUIStore = create<UIStore>((set) => ({
  // Initial state
  isHeaderHidden: false,
  animations: defaultAnimations,
  workspaceState: defaultWorkspaceState,
  activeChallenge: null,

  // Header actions
  setHeaderHidden: (hidden) => set({ isHeaderHidden: hidden }),

  // Workspace actions
  setSidebarCollapsed: (collapsed) =>
    set(state => ({
      workspaceState: { ...state.workspaceState, sidebarCollapsed: collapsed }
    })),

  setSidebarWidth: (width) =>
    set(state => ({
      workspaceState: { ...state.workspaceState, sidebarWidth: width }
    })),

  setFullScreen: (fullScreen) =>
    set(state => ({
      workspaceState: { ...state.workspaceState, isFullScreen: fullScreen }
    })),

  setActiveService: (service) => {
    // Save preference to localStorage
    try {
      localStorage.setItem('dojo-preferred-service', service)
    } catch (error) {
      console.warn('Failed to save service preference:', error)
    }

    set(state => ({
      workspaceState: {
        ...state.workspaceState,
        activeService: service,
        preferredService: service
      }
    }))
  },

  setCommandPaletteOpen: (open) =>
    set(state => ({
      workspaceState: { ...state.workspaceState, commandPaletteOpen: open }
    })),

  setWorkspaceHeaderHidden: (hidden) =>
    set(state => ({
      workspaceState: { ...state.workspaceState, workspaceHeaderHidden: hidden }
    })),

  // Active Challenge actions
  setActiveChallenge: (challenge) => set({ activeChallenge: challenge }),

  fetchActiveChallenge: async () => {
    // This method is deprecated - active challenge is now handled in Layout component
    console.log('fetchActiveChallenge called but deprecated - active challenge handled in Layout')
  }
}))

// Selectors for common use cases
export const useHeaderState = () => {
  const isHeaderHidden = useUIStore(state => state.isHeaderHidden)
  const setHeaderHidden = useUIStore(state => state.setHeaderHidden)

  return {
    isHeaderHidden,
    setHeaderHidden
  }
}

export const useActiveChallenge = () => useUIStore(state => ({
  activeChallenge: state.activeChallenge,
  setActiveChallenge: state.setActiveChallenge
}))

// Animation selector for easy access across components
export const useAnimations = () => useUIStore(state => state.animations)
