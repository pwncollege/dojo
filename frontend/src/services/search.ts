import { apiClient } from './api'

export interface SearchResult {
  id: string
  name: string
  link: string
  match?: string
}

export interface DojoSearchResult extends SearchResult {
  // dojo specific fields if needed
}

export interface ModuleSearchResult extends SearchResult {
  dojo: {
    id: string
    name: string
    link: string
  }
}

export interface ChallengeSearchResult extends SearchResult {
  module: {
    id: string
    name: string
    link: string
  }
  dojo: {
    id: string
    name: string
    link: string
  }
}

export interface SearchResponse {
  success: boolean
  results: {
    dojos: DojoSearchResult[]
    modules: ModuleSearchResult[]
    challenges: ChallengeSearchResult[]
  }
}

class SearchService {
  async search(query: string): Promise<SearchResponse> {
    if (!query || query.length < 2) {
      return {
        success: true,
        results: {
          dojos: [],
          modules: [],
          challenges: []
        }
      }
    }

    return apiClient.get<SearchResponse>(`/search?q=${encodeURIComponent(query)}`)
  }
}

export const searchService = new SearchService()