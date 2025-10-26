import { dojoApiClient } from './api'

export interface WorkspaceResponse {
  success: boolean
  active: boolean
  iframe_src?: string
  service?: string
  error?: string
  current_challenge?: {
    dojo_id: string
    module_id: string
    challenge_id: string
    challenge_name?: string // Optional since API might not provide it
  }
}

export interface NextChallengeResponse {
  success: boolean
  error?: string
  dojo?: string
  module?: string
  challenge?: string
  challenge_index?: number
  new_module?: boolean
}

class WorkspaceService {
  // Get current active challenge (without starting workspace)
  async getCurrentChallenge(): Promise<WorkspaceResponse> {
    return dojoApiClient.get<WorkspaceResponse>('/workspace')
  }

  // Get workspace iframe URL for a service
  async getWorkspace(params: {
    user?: string
    password?: string
    service?: string
    theme?: string
  }): Promise<WorkspaceResponse> {
    const searchParams = new URLSearchParams()
    if (params.user) searchParams.append('user', params.user)
    if (params.password) searchParams.append('password', params.password)
    if (params.service) searchParams.append('service', params.service)
    if (params.theme) searchParams.append('theme', params.theme)

    const query = searchParams.toString()
    return dojoApiClient.get<WorkspaceResponse>(`/workspace${query ? '?' + query : ''}`)
  }

  // Reset user's home directory
  async resetHome(): Promise<{ success: boolean; error?: string; message?: string }> {
    return dojoApiClient.post('/workspace/reset_home')
  }

  // Terminate/kill the current workspace
  async terminateWorkspace(): Promise<{ success: boolean; error?: string; message?: string }> {
    return dojoApiClient.delete('/docker')
  }

  // Get next challenge in sequence
  async getNextChallenge(): Promise<NextChallengeResponse> {
    return dojoApiClient.get<NextChallengeResponse>('/docker/next')
  }
}

export const workspaceService = new WorkspaceService()