import { apiClient } from './api'

// Helper function to convert API links to frontend URL format
function convertApiLinkToUrl(apiLink: string): string {
  if (apiLink.startsWith('/')) {
    const pathParts = apiLink.split('/').filter(Boolean)

    if (pathParts.length === 1) {
      // Dojo: /dojoid -> /dojo/[dojoId]
      return `/dojo/${pathParts[0]}`
    } else if (pathParts.length === 2) {
      // Module: /dojoid/moduleid -> /dojo/[dojoId]/module/[moduleId]
      return `/dojo/${pathParts[0]}/module/${pathParts[1]}`
    } else if (pathParts.length === 3) {
      // Challenge: /dojoid/moduleid/challengeid -> /dojo/[dojoId]/module/[moduleId]/workspace/challenge/[challengeId]
      return `/dojo/${pathParts[0]}/module/${pathParts[1]}/workspace/challenge/${pathParts[2]}`
    }
  }

  return apiLink
}

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

    const response = await apiClient.get<SearchResponse>(`/search?q=${encodeURIComponent(query)}`)

    // Convert all search result links to frontend URLs
    return {
      ...response,
      results: {
        dojos: response.results.dojos.map(dojo => ({
          ...dojo,
          link: convertApiLinkToUrl(dojo.link)
        })),
        modules: response.results.modules.map(module => ({
          ...module,
          link: convertApiLinkToUrl(module.link)
        })),
        challenges: response.results.challenges.map(challenge => ({
          ...challenge,
          link: convertApiLinkToUrl(challenge.link)
        }))
      }
    }
  }
}

export const searchService = new SearchService()