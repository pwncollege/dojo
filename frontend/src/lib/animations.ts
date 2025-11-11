import { useAnimations } from '@/stores'

/**
 * Animation utilities for consistent timing across the app
 */

// CSS transition durations (in seconds)
export const animationDurations = {
  fast: '0.15s',    // hover effects, micro-interactions
  medium: '0.25s',  // page transitions, content switching
  slow: '0.4s',     // modals, complex layout changes
} as const

// CSS easing function
export const animationEasing = 'cubic-bezier(0.25, 0.46, 0.45, 0.94)' // Apple-grade easing

// Framer Motion transition presets
export const motionPresets = {
  fast: {
    duration: 0.15,
    ease: [0.25, 0.46, 0.45, 0.94]
  },
  medium: {
    duration: 0.25,
    ease: [0.25, 0.46, 0.45, 0.94]
  },
  slow: {
    duration: 0.4,
    ease: [0.25, 0.46, 0.45, 0.94]
  }
} as const

/**
 * Hook to get CSS transition string for Tailwind classes
 * @param speed - Animation speed preset
 * @returns CSS transition string
 */
export const useCSSTransition = (speed: keyof typeof animationDurations = 'medium') => {
  return `transition-all duration-[${animationDurations[speed]}] ease-[${animationEasing}]`
}

/**
 * Get CSS transition string directly (for non-hook contexts)
 * @param speed - Animation speed preset
 * @returns CSS transition string
 */
export const getCSSTransition = (speed: keyof typeof animationDurations = 'medium') => {
  return `transition-all duration-[${animationDurations[speed]}] ease-[${animationEasing}]`
}