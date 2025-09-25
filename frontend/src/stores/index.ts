// Main stores
export { useDojoStore } from './dojoStore'
export { useAuthStore } from './authStore'
export { useUIStore, useHeaderState, useAnimations } from './uiStore'
export {
  useWorkspaceStore,
  useWorkspaceSidebar,
  useWorkspaceService,
  useWorkspaceView,
  useWorkspaceChallenge,
  useWorkspaceResource
} from './workspaceStore'

// Store initialization
import { useAuthStore } from './authStore'
import { useDojoStore } from './dojoStore'
import { useUIStore } from './uiStore'

// Initialize stores on app start
let isInitializing = false
export const initializeStores = async () => {
  if (isInitializing) {
    return
  }

  isInitializing = true

  try {
    // 1. Initialize auth store first
    await useAuthStore.getState().fetchCurrentUser()

    // Note: Dojos and modules are now fetched server-side, not in client store
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

