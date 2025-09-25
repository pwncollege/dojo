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

  // Actions - Header
  setHeaderHidden: (hidden: boolean) => void
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

  // Header actions
  setHeaderHidden: (hidden) => set({ isHeaderHidden: hidden })
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

// Animation selector for easy access across components
export const useAnimations = () => useUIStore(state => state.animations)
