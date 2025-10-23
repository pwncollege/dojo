import { create } from 'zustand'
import { subscribeWithSelector } from 'zustand/middleware'
import { dojoService } from '@/services/dojo'

// Cache for memoized selectors
const selectorCache = new Map()

interface Dojo {
  id: string
  name: string
  description?: string
  official: boolean
  award?: {
    belt?: string
    emoji?: string
  }
}

interface Module {
  id: string
  name: string
  description?: string
  challenges: Challenge[]
}

interface Challenge {
  id: string
  name: string
  description?: string
  required: boolean
  solved?: boolean
}

interface Solve {
  user_id: string
  dojo_id: string
  module_id: string
  challenge_id: string
  timestamp: string
}

interface DojoStore {
  // Data (dojos and modules now come from server-side rendering)
  solves: Record<string, Solve[]>

  // Loading states (only solves need client-side loading now)
  loadingSolves: Record<string, boolean>

  // Error states (only solves need client-side error handling now)
  solveError: Record<string, string | null>

  // Actions
  fetchSolves: (dojoId: string, username?: string) => Promise<void>
  addSolve: (dojoId: string, moduleId: string, challengeId: string, userId?: string) => void

  // Selectors
  getSolvesByDojo: (dojoId: string) => Solve[]
}

export const useDojoStore = create<DojoStore>()(
  subscribeWithSelector((set, get) => ({
    // Initial state
    solves: {},
    loadingSolves: {},
    solveError: {},

    // Actions

    fetchSolves: async (dojoId: string, username?: string) => {
      const key = `${dojoId}-${username || 'all'}`
      const state = get()
      // Prevent duplicate fetches if already loading or have data
      if (state.loadingSolves[key] || state.solves[key]) {
        return
      }

      set(state => ({
        loadingSolves: { ...state.loadingSolves, [key]: true },
        solveError: { ...state.solveError, [key]: null }
      }))
      try {
        const response = await dojoService.getDojoSolves(dojoId, username)
        set(state => ({
          solves: { ...state.solves, [key]: response.solves || [] },
          loadingSolves: { ...state.loadingSolves, [key]: false }
        }))
        // Clear stats cache when solves change
        selectorCache.delete(`stats-${dojoId}`)
      } catch (error) {
        set(state => ({
          solveError: {
            ...state.solveError,
            [key]: error instanceof Error ? error.message : 'Failed to fetch solves'
          },
          loadingSolves: { ...state.loadingSolves, [key]: false }
        }))
      }
    },

    addSolve: (dojoId: string, moduleId: string, challengeId: string, userId?: string) => {
      const key = `${dojoId}-${userId || 'all'}`
      const newSolve: Solve = {
        user_id: userId || 'current-user',
        dojo_id: dojoId,
        module_id: moduleId,
        challenge_id: challengeId,
        timestamp: new Date().toISOString()
      }

      set(state => {
        const existingSolves = state.solves[key] || []
        // Check if solve already exists to avoid duplicates
        const alreadyExists = existingSolves.some(solve =>
          solve.module_id === moduleId && solve.challenge_id === challengeId
        )

        if (alreadyExists) {
          return state // No change if already solved
        }

        return {
          solves: {
            ...state.solves,
            [key]: [...existingSolves, newSolve]
          }
        }
      })

    },

    // Selectors
    getSolvesByDojo: (dojoId: string) => {
      return get().solves[`${dojoId}-all`] || []
    }
  }))
)