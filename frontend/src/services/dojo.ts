import { apiClient, ctfdApiClient } from './api'
import type { DojoModule, Resource, Challenge } from '@/types/api'

// Helper function to process modules and add legacy arrays from unified_items
function processModule(module: any): DojoModule & { challenges: Challenge[], resources?: Resource[] } {
  if (!module.unified_items) {
    // If no unified_items, return as-is (fallback for old modules)
    return module
  }

  // Extract challenges and resources from unified_items
  const challenges: Challenge[] = module.unified_items
    .filter((item: any) => item.item_type === 'challenge')
    .map((item: any) => ({
      id: item.id,
      name: item.name || 'Untitled Challenge',
      required: item.required || false,
      description: item.description,
      // Add any other challenge-specific fields
    }))

  const resources: Resource[] = module.unified_items
    .filter((item: any) => item.item_type === 'resource' && item.type !== 'header')
    .map((item: any) => ({
      id: item.id,
      name: item.name || 'Untitled Resource',
      type: item.type || 'markdown',
      content: item.content,
      video: item.video,
      playlist: item.playlist,
      slides: item.slides,
      expandable: item.expandable,
    }))

  return {
    ...module,
    challenges,
    resources: resources.length > 0 ? resources : undefined
  }
}

export interface DojoListResponse {
  success: boolean
  dojos: Array<{
    id: string
    name: string
    description?: string
    official: boolean
    award?: {
      belt?: string
      emoji?: string
    }
    modules: number
    challenges: number
    active_hackers: number
  }>
}

export interface DojoModulesResponse {
  success: boolean
  modules: Array<{
    id: string
    name: string
    description?: string
    unified_items?: Array<{
      item_type: 'resource' | 'challenge'
      id: string
      name?: string
      type?: 'markdown' | 'lecture' | 'header'
      content?: string
      video?: string
      playlist?: string
      slides?: string
      expandable?: boolean
      description?: string
      required?: boolean
    }>
    resources?: Array<{
      id: string
      name: string
      type: 'markdown' | 'lecture' | 'header'
      content?: string
      video?: string
      playlist?: string
      slides?: string
      expandable?: boolean
    }>
    challenges: Array<{
      id: string
      name: string
      required: boolean
      description?: string
    }>
  }>
  stats?: {
    users: number
    challenges: number
    visible_challenges: number
    solves: number
    recent_solves: Array<{
      challenge_name: string
      date: string
      date_display: string
    }>
    trends: {
      solves: number
      users: number
      active: number
      challenges: number
    }
    chart_data: {
      labels: string[]
      solves: number[]
      users: number[]
    }
  }
}

export interface DojoDetailResponse {
  success: boolean
  dojo: {
    id: string
    name: string
    description?: string
    official: boolean
    award?: {
      belt?: string
      emoji?: string
    }
    modules: Array<{
      id: string
      name: string
      description?: string
      unified_items?: Array<{
        item_type: 'resource' | 'challenge'
        id: string
        name?: string
        type?: 'markdown' | 'lecture' | 'header'
        content?: string
        video?: string
        playlist?: string
        slides?: string
        expandable?: boolean
        description?: string
        required?: boolean
      }>
      resources?: Array<{
        id: string
        name: string
        type: 'markdown' | 'lecture' | 'header'
        content?: string
        video?: string
        playlist?: string
        slides?: string
        expandable?: boolean
      }>
      challenges: Array<{
        id: string
        name: string
        required: boolean
        description?: string
      }>
    }>
    stats?: {
      users: number
      challenges: number
      visible_challenges: number
      solves: number
      recent_solves: Array<{
        challenge_name: string
        date: string
        date_display: string
      }>
      trends: {
        solves: number
        users: number
        active: number
        challenges: number
      }
      chart_data: {
        labels: string[]
        solves: number[]
        users: number[]
      }
    }
  }
}

export interface DojoSolvesResponse {
  success: boolean
  solves: Array<{
    timestamp: string
    module_id: string
    challenge_id: string
    user_id?: string
    dojo_id?: string
  }>
}

export interface DojoCourseResponse {
  success: boolean
  course: {
    syllabus?: any
    scripts?: any
    student?: {
      token: string
      user_id: number
      [key: string]: any
    }
  }
}

export interface CreateDojoData {
  repository: string
  spec?: string
  public_key?: string
  private_key?: string
}

export interface SolveSubmission {
  [key: string]: any // Challenge-specific submission data
}

export interface SurveyResponse {
  response: string
}

class DojoService {
  // Get all available dojos
  async getDojos(): Promise<DojoListResponse> {
    // Check if API URLs are available (for server-side rendering)
    return apiClient.get<DojoListResponse>('/dojos')
  }

  // Create a new dojo
  async createDojo(data: CreateDojoData): Promise<{ success: boolean; dojo?: string; error?: string }> {
    return apiClient.post('/dojos/create', data)
  }

  // Get dojo modules
  async getDojoModules(dojoId: string): Promise<DojoModulesResponse> {
    const response = await apiClient.get<DojoModulesResponse>(`/dojos/${dojoId}/modules`)

    // Process modules to add legacy arrays
    return {
      ...response,
      modules: response.modules.map(processModule)
    }
  }

  // Get dojo details with modules
  async getDojoDetail(dojoId: string): Promise<DojoDetailResponse> {
    try {
      // For now, combine separate API calls - in future this could be a single endpoint
      const [dojoResponse, modulesResponse] = await Promise.all([
        this.getDojos().then(res => res.dojos.find(d => d.id === dojoId)),
        this.getDojoModules(dojoId)
      ])

      if (!dojoResponse) {
        throw new Error(`Dojo ${dojoId} not found`)
      }

      return {
        success: true,
        dojo: {
          id: dojoResponse.id,
          name: dojoResponse.name,
          description: dojoResponse.description,
          official: dojoResponse.official,
          award: dojoResponse.award,
          modules: (modulesResponse.modules || []).map(processModule),
          stats: modulesResponse.stats
        }
      }
    } catch (error) {
      throw new Error(`Failed to fetch dojo details: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  // Get user's solves in a dojo
  async getDojoSolves(dojoId: string, username?: string, after?: string): Promise<DojoSolvesResponse> {
    const params = new URLSearchParams()
    if (username) params.append('username', username)
    if (after) params.append('after', after)
    
    const query = params.toString()
    return apiClient.get<DojoSolvesResponse>(`/dojos/${dojoId}/solves${query ? '?' + query : ''}`)
  }

  // Get dojo course information
  async getDojoCourse(dojoId: string): Promise<DojoCourseResponse> {
    return apiClient.get<DojoCourseResponse>(`/dojos/${dojoId}/course`)
  }

  // Submit solution for a challenge using dojo solve endpoint
  async submitChallengeSolution(
    dojoId: string,
    moduleId: string,
    challengeId: string,
    submission: SolveSubmission
  ): Promise<{ success: boolean; status?: string; error?: string }> {
    return apiClient.post(`/dojos/${dojoId}/${moduleId}/${challengeId}/solve`, submission)
  }

  // Get challenge description
  async getChallengeDescription(
    dojoId: string, 
    moduleId: string, 
    challengeId: string
  ): Promise<{ success: boolean; description?: string; error?: string }> {
    return apiClient.get(`/dojos/${dojoId}/${moduleId}/${challengeId}/description`)
  }

  // Get challenge survey
  async getChallengeSurvey(
    dojoId: string, 
    moduleId: string, 
    challengeId: string
  ): Promise<{ 
    success: boolean
    type: string
    prompt?: string
    data?: any
    probability?: number
  }> {
    return apiClient.get(`/dojos/${dojoId}/${moduleId}/${challengeId}/surveys`)
  }

  // Submit survey response
  async submitSurveyResponse(
    dojoId: string, 
    moduleId: string, 
    challengeId: string, 
    response: SurveyResponse
  ): Promise<{ success: boolean; error?: string }> {
    return apiClient.post(`/dojos/${dojoId}/${moduleId}/${challengeId}/surveys`, response)
  }

  // Admin endpoints
  async promoteAdmin(dojoId: string, userId: number): Promise<{ success: boolean; error?: string }> {
    return apiClient.post(`/dojos/${dojoId}/admins/promote`, { user_id: userId })
  }

  async promoteDojo(dojoId: string): Promise<{ success: boolean }> {
    return apiClient.post(`/dojos/${dojoId}/promote`)
  }

  async pruneAwards(dojoId: string): Promise<{ success: boolean; pruned_awards?: number }> {
    return apiClient.post(`/dojos/${dojoId}/awards/prune`)
  }

  // Course admin endpoints
  async getCourseStudents(dojoId: string): Promise<{
    success: boolean
    students: {
      [token: string]: {
        token?: string
        user_id?: number
        [key: string]: any
      }
    }
  }> {
    return apiClient.get(`/dojos/${dojoId}/course/students`)
  }

  async getCourseSolves(dojoId: string, after?: string): Promise<{
    success: boolean
    solves: Array<{
      timestamp: string
      student_token: string
      user_id: number
      module_id: string
      challenge_id: string
    }>
  }> {
    const params = new URLSearchParams()
    if (after) params.append('after', after)
    
    const query = params.toString()
    return apiClient.get(`/dojos/${dojoId}/course/solves${query ? '?' + query : ''}`)
  }
}

export const dojoService = new DojoService()
