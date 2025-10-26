import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { dojoService, type CreateDojoData, type SolveSubmission, type SurveyResponse } from '@/services/dojo'
import { dojoApiClient } from '@/services/api'
import { queryKeys } from '@/lib/queryClient'

// Get all dojos
export function useDojos() {
  return useQuery({
    queryKey: queryKeys.dojos,
    queryFn: () => dojoService.getDojos(),
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

// Get dojo modules
export function useDojoModules(dojoId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.dojoModules(dojoId),
    queryFn: () => dojoService.getDojoModules(dojoId),
    enabled: enabled && !!dojoId,
    staleTime: 2 * 60 * 1000, // 2 minutes for modules
  })
}

// Get dojo solves for a user
export function useDojoSolves(dojoId: string, username?: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.dojoSolves(dojoId, username),
    queryFn: () => dojoService.getDojoSolves(dojoId, username),
    enabled: enabled && !!dojoId,
    staleTime: 30 * 1000, // 30 seconds for solve data (more dynamic)
  })
}

// Get dojo course information
export function useDojoCourse(dojoId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.dojoCourse(dojoId),
    queryFn: () => dojoService.getDojoCourse(dojoId),
    enabled: enabled && !!dojoId,
    staleTime: 5 * 60 * 1000, // 5 minutes for course info
  })
}

// Get challenge description
export function useChallengeDescription(
  dojoId: string, 
  moduleId: string, 
  challengeId: string,
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.challengeDescription(dojoId, moduleId, challengeId),
    queryFn: () => dojoService.getChallengeDescription(dojoId, moduleId, challengeId),
    enabled: enabled && !!dojoId && !!moduleId && !!challengeId,
    staleTime: 10 * 60 * 1000, // 10 minutes for descriptions
  })
}

// Get challenge survey
export function useChallengeSurvey(
  dojoId: string, 
  moduleId: string, 
  challengeId: string,
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.challengeSurvey(dojoId, moduleId, challengeId),
    queryFn: () => dojoService.getChallengeSurvey(dojoId, moduleId, challengeId),
    enabled: enabled && !!dojoId && !!moduleId && !!challengeId,
    staleTime: 5 * 60 * 1000, // 5 minutes for surveys
  })
}

// Mutations
export function useCreateDojo() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (data: CreateDojoData) => dojoService.createDojo(data),
    onSuccess: () => {
      // Invalidate dojos list to refetch
      queryClient.invalidateQueries({ queryKey: queryKeys.dojos })
    },
  })
}

export function useSubmitChallengeSolution() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ 
      dojoId, 
      moduleId, 
      challengeId, 
      submission 
    }: {
      dojoId: string
      moduleId: string
      challengeId: string
      submission: SolveSubmission
    }) => dojoService.submitChallengeSolution(dojoId, moduleId, challengeId, submission),
    onSuccess: (_, variables) => {
      // Invalidate related queries to update solve status
      queryClient.invalidateQueries({ 
        queryKey: queryKeys.dojoSolves(variables.dojoId) 
      })
      queryClient.invalidateQueries({ 
        queryKey: queryKeys.dojoModules(variables.dojoId) 
      })
    },
  })
}

export function useSubmitSurveyResponse() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ 
      dojoId, 
      moduleId, 
      challengeId, 
      response 
    }: {
      dojoId: string
      moduleId: string
      challengeId: string
      response: SurveyResponse
    }) => dojoService.submitSurveyResponse(dojoId, moduleId, challengeId, response),
    onSuccess: (_, variables) => {
      // Invalidate survey query
      queryClient.invalidateQueries({ 
        queryKey: queryKeys.challengeSurvey(variables.dojoId, variables.moduleId, variables.challengeId) 
      })
    },
  })
}

// Admin mutations
export function usePromoteAdmin() {
  return useMutation({
    mutationFn: ({ dojoId, userId }: { dojoId: string; userId: number }) => 
      dojoService.promoteAdmin(dojoId, userId),
  })
}

export function usePromoteDojo() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (dojoId: string) => dojoService.promoteDojo(dojoId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.dojos })
    },
  })
}

export function usePruneAwards() {
  return useMutation({
    mutationFn: (dojoId: string) => dojoService.pruneAwards(dojoId),
  })
}

export function useStartChallenge() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ dojoId, moduleId, challengeId, practice = false }: {
      dojoId: string
      moduleId: string
      challengeId: string
      practice?: boolean
    }) => dojoApiClient.post('/docker', {
      dojo: dojoId,
      module: moduleId,
      challenge: challengeId,
      practice
    }),
    onSuccess: () => {
      // Invalidate workspace queries to refetch state
      queryClient.invalidateQueries({ queryKey: ['workspace'] })
    },
  })
}