// Main stores
export { useDojoStore } from './dojoStore'
export { useAuthStore } from './authStore'
export { useUIStore, useHeaderState, useActiveChallenge, useAnimations } from './uiStore'

// Store initialization
import { useAuthStore } from './authStore'
import { useDojoStore } from './dojoStore'
import { useUIStore } from './uiStore'

// Initialize stores on app start
let isInitializing = false
export const initializeStores = async () => {
  if (isInitializing) {
    console.log('Store initialization already in progress, skipping...')
    return
  }

  isInitializing = true
  console.log('=== INITIALIZING STORES ===')

  try {
    // 1. Initialize auth store first
    console.log('1. Fetching current user...')
    await useAuthStore.getState().fetchCurrentUser()

    // Check final auth state
    const authState = useAuthStore.getState()
    console.log('1.1. Auth state after fetch:', {
      isAuthenticated: authState.isAuthenticated,
      user: authState.user,
      error: authState.authError
    })

    // Note: Dojos and modules are now fetched server-side, not in client store
    console.log('2. Dojos and modules are now fetched server-side')

    console.log('=== STORE INITIALIZATION COMPLETE ===')
  } catch (error) {
    console.error('Store initialization failed:', error)
  } finally {
    isInitializing = false
  }
}

// Helper hooks for common patterns
export const useAuthenticatedUser = () => {
  const user = useAuthStore(state => state.user)
  const isAuthenticated = useAuthStore(state => state.isAuthenticated)
  const isAdmin = useAuthStore(state => state.user?.type === 'admin')
  const displayName = useAuthStore(state => state.user?.username || 'Unknown User')

  return {
    user,
    isAuthenticated,
    isAdmin,
    displayName,
    // Derived properties that match the old hook interface
    name: user?.username,
    email: user?.email,
    admin: user?.type === 'admin'
  }
}

