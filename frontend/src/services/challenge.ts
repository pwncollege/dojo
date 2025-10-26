import { apiClient } from './api'

// Challenge-related operations are mainly handled through dojo endpoints
// This service provides search and other general challenge operations

export interface SearchResponse {
  success: boolean
  results: Array<{
    type: string
    id: string
    name: string
    description?: string
    dojo?: {
      id: string
      name: string
    }
    module?: {
      id: string
      name: string
    }
  }>
}

class ChallengeService {
  // Search across all content
  async search(query: string): Promise<SearchResponse> {
    const params = new URLSearchParams({ q: query })
    return apiClient.get<SearchResponse>(`/api/v1/search?${params}`)
  }
}

export const challengeService = new ChallengeService()