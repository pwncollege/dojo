import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '@/services/api'

// Optimal configuration for performance
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Cache data for 5 minutes by default
      staleTime: 5 * 60 * 1000,
      // Keep cached data for 10 minutes after component unmount
      gcTime: 10 * 60 * 1000,
      // Retry failed requests 3 times with exponential backoff
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          // Don't retry client errors (4xx)
          return false
        }
        return failureCount < 3
      },
      // Refetch on window focus for fresh data
      refetchOnWindowFocus: false,
      // Don't refetch on reconnect by default (can be enabled per query)
      refetchOnReconnect: true,
      // Enable network mode handling
      networkMode: 'online',
    },
    mutations: {
      // Retry mutations only once
      retry: 1,
      // Network mode for mutations
      networkMode: 'online',
    },
  },
})

// Query key factories for consistent caching
export const queryKeys = {
  // Dojos
  dojos: ['dojos'] as const,
  dojo: (id: string) => ['dojos', id] as const,
  dojoModules: (id: string) => ['dojos', id, 'modules'] as const,
  dojoSolves: (id: string, username?: string) => ['dojos', id, 'solves', username] as const,
  dojoCourse: (id: string) => ['dojos', id, 'course'] as const,
  
  // Challenges
  challengeDescription: (dojoId: string, moduleId: string, challengeId: string) =>
    ['dojos', dojoId, 'modules', moduleId, 'challenges', challengeId, 'description'] as const,
  challengeSurvey: (dojoId: string, moduleId: string, challengeId: string) =>
    ['dojos', dojoId, 'modules', moduleId, 'challenges', challengeId, 'survey'] as const,
    
  // Workspace
  workspace: (params?: Record<string, string>) => ['workspace', params] as const,
  
  // Search
  search: (query: string) => ['search', query] as const,
  
  // Auth
  currentUser: ['auth', 'me'] as const,
} as const