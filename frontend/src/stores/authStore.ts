import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { authService, type LoginCredentials, type RegisterData } from '@/services/auth'

interface User {
  id: string
  username: string
  email: string
  type: 'user' | 'admin'
}

interface AuthStore {
  // Data
  user: User | null
  isAuthenticated: boolean

  // Loading states
  isLoading: boolean
  loginLoading: boolean
  registerLoading: boolean

  // Error states
  authError: string | null

  // Actions
  login: (credentials: LoginCredentials) => Promise<void>
  register: (data: RegisterData) => Promise<void>
  logout: () => Promise<void>
  fetchCurrentUser: () => Promise<void>
  clearError: () => void

  // Computed properties
  isAdmin: () => boolean
  displayName: () => string
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      // Initial state
      user: null,
      isAuthenticated: false,
      isLoading: false,
      loginLoading: false,
      registerLoading: false,
      authError: null,

      // Actions
      login: async (credentials: LoginCredentials) => {
        set({ loginLoading: true, authError: null })
        try {
          const response = await authService.login(credentials)
          if (response.success && response.data) {
            set({
              user: response.data,
              isAuthenticated: true,
              loginLoading: false
            })
            // Rehydrate stores after login
            const { useDojoStore } = await import('./dojoStore')
            useDojoStore.getState().rehydrate?.()
          } else {
            throw new Error(response.errors?.join(', ') || 'Login failed')
          }
        } catch (error) {
          set({
            authError: error instanceof Error ? error.message : 'Login failed',
            loginLoading: false
          })
          throw error
        }
      },

      register: async (data: RegisterData) => {
        set({ registerLoading: true, authError: null })
        try {
          const response = await authService.register(data)
          if (response.success && response.data) {
            set({
              user: response.data,
              isAuthenticated: true,
              registerLoading: false
            })
          } else {
            throw new Error(response.errors?.join(', ') || 'Registration failed')
          }
        } catch (error) {
          set({
            authError: error instanceof Error ? error.message : 'Registration failed',
            registerLoading: false
          })
          throw error
        }
      },

      logout: async () => {
        try {
          await authService.logout()
        } catch (error) {
          // Continue with logout even if API call fails
          console.warn('Logout API call failed:', error)
        } finally {
          set({
            user: null,
            isAuthenticated: false,
            authError: null
          })
        }
      },

      fetchCurrentUser: async () => {
        set({ isLoading: true })
        try {
          const response = await authService.fetchCurrentUser()

          if (response.success && response.data) {
            set({
              user: {
                id: response.data.id?.toString() || response.data.user_id?.toString(),
                username: response.data.name || response.data.username,
                email: response.data.email,
                type: response.data.type || 'user'
              },
              isAuthenticated: true,
              isLoading: false,
              authError: null
            })
          } else {
            set({
              user: null,
              isAuthenticated: false,
              isLoading: false,
              authError: response.error || 'Not authenticated'
            })
          }
        } catch (error) {
          set({
            user: null,
            isAuthenticated: false,
            isLoading: false,
            authError: error instanceof Error ? error.message : 'Failed to fetch user'
          })
        }
      },

      clearError: () => {
        set({ authError: null })
      },

      // Computed properties
      isAdmin: () => {
        const { user } = get()
        return user?.type === 'admin'
      },

      displayName: () => {
        const { user } = get()
        return user?.username || 'Unknown User'
      }
    }),
    {
      name: 'auth-store',
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated
      })
    }
  )
)