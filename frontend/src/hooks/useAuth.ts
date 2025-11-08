import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { authService, type LoginCredentials, type RegisterData, type ChangePasswordData, type ResetPasswordData } from '@/services/auth'
import { queryKeys } from '@/lib/queryClient'

// Get current user
export function useCurrentUser(enabled = true) {
  return useQuery({
    queryKey: queryKeys.currentUser,
    queryFn: () => Promise.resolve(authService.getCurrentUser()),
    enabled: enabled && authService.isAuthenticated(),
    staleTime: 10 * 60 * 1000, // 10 minutes for user data
    retry: false, // Don't retry auth requests
  })
}

// Auth mutations
export function useLogin() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (credentials: LoginCredentials) => authService.login(credentials),
    onSuccess: (response) => {
      if (response.success && response.data) {
        // Update current user cache with the user data from response
        queryClient.setQueryData(queryKeys.currentUser, response.data)

        // Invalidate all queries to refetch with new auth
        queryClient.invalidateQueries()
      }
    },
  })
}

export function useRegister() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: RegisterData) => authService.register(data),
    onSuccess: (response) => {
      if (response.success && response.data) {
        // Update current user cache with the user data from response
        queryClient.setQueryData(queryKeys.currentUser, response.data)

        // Invalidate all queries to refetch with new auth
        queryClient.invalidateQueries()
      }
    },
  })
}

export function useLogout() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => authService.logout(),
    onSuccess: () => {
      // Clear all queries on logout
      queryClient.clear()

      // Remove current user from cache
      queryClient.removeQueries({ queryKey: queryKeys.currentUser })
    },
  })
}

export function useUpdateProfile() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (data: Partial<Parameters<typeof authService.updateProfile>[0]>) => 
      authService.updateProfile(data),
    onSuccess: (response) => {
      if (response.success && response.user) {
        // Update current user cache
        queryClient.setQueryData(queryKeys.currentUser, response)
      }
    },
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (data: ChangePasswordData) => authService.changePassword(data),
  })
}

export function useResetPassword() {
  return useMutation({
    mutationFn: ({ token, password }: { token: string; password: string }) =>
      authService.resetPassword(token, password),
  })
}


// Helper hooks
export function useIsAuthenticated() {
  const { data: currentUser, isLoading } = useCurrentUser()

  return {
    isAuthenticated: !!currentUser && authService.isAuthenticated(),
    isLoading,
    user: currentUser ? {
      name: currentUser.username,
      email: currentUser.email,
      admin: currentUser.type === 'admin'
    } : null
  }
}