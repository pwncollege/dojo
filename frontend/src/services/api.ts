export const PROTOCOL = process.env.NEXT_PUBLIC_DOJO_ENV === 'production' ? 'https' : 'http'
const  CTFD_API_BASE_URL = `${PROTOCOL}://${process.env.NEXT_PUBLIC_DOJO_HOST}/api/v1`
const  DOJO_API_BASE_URL = `${PROTOCOL}://${process.env.NEXT_PUBLIC_DOJO_HOST}/pwncollege_api/v1`

export interface ApiResponse<T> {
  data?: T
  error?: string
  message?: string
}

export class ApiError extends Error {
  public status: number
  public response?: any

  constructor(message: string, status: number, response?: any) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.response = response
  }
}

class ApiClient {
  private baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer fake`,
    }

    // Add any additional headers
    if (options.headers) {
      Object.assign(headers, options.headers)
    }

    try {
      const response = await fetch(url, {
        ...options,
        headers,
        credentials: 'include', // Include cookies for auth
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))

        // If the response has a 'success' field, it's a structured response
        // even if the HTTP status is not 2xx (common with auth endpoints)
        if ('success' in errorData) {
          return errorData as T
        }

        throw new ApiError(
          errorData.message || `HTTP ${response.status}`,
          response.status,
          errorData
        )
      }

      const contentType = response.headers.get('content-type')
      if (contentType && contentType.includes('application/json')) {
        return await response.json()
      }
      
      return response.text() as unknown as T
    } catch (error) {
      if (error instanceof ApiError) {
        throw error
      }
      throw new ApiError('Network error', 0, error)
    }
  }

  async get<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'GET' })
  }

  async post<T>(endpoint: string, data?: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined,
    })
  }

  async put<T>(endpoint: string, data?: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined,
    })
  }

  async patch<T>(endpoint: string, data?: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PATCH',
      body: data ? JSON.stringify(data) : undefined,
    })
  }

  async delete<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'DELETE' })
  }
}

// Create separate API clients
export const ctfdApiClient = new ApiClient(CTFD_API_BASE_URL)
export const dojoApiClient = new ApiClient(DOJO_API_BASE_URL)


// Keep the default client pointing to dojo API for backwards compatibility
export const apiClient = dojoApiClient
