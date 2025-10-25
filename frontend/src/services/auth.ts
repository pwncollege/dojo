import { dojoApiClient} from './api'

export interface LoginCredentials {
  name: string  // username or email
  password: string
  remember_me?: boolean
}

export interface RegisterData {
  name: string
  email: string
  password: string
  affiliation?: string
  country?: string
  [key: string]: any // For custom fields like 'fields[1]'
}

export interface ResetPasswordData {
  email: string
}

export interface ChangePasswordData {
  currentPassword: string
  newPassword: string
}

export interface AuthResponse {
  success: boolean
  data?: {
    user_id: number
    username: string
    email: string
    type: string
    verified: boolean
    team_id?: number
  }
  errors?: string[]
  message?: string
}

class AuthService {
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const response = await dojoApiClient.post<AuthResponse>('/auth/login', credentials)

    if (response.success && response.data) {
      // Store user data locally
      localStorage.setItem('ctfd_user', JSON.stringify(response.data))
    }

    return response
  }

  async register(data: RegisterData): Promise<AuthResponse> {
    const response = await dojoApiClient.post<AuthResponse>('/auth/register', data)

    if (response.success && response.data) {
      // Store user data locally
      localStorage.setItem('ctfd_user', JSON.stringify(response.data))
    }

    return response
  }

  async logout(): Promise<{ success: boolean }> {
    // Clear the session cookie by calling logout endpoint
    try {
      await dojoApiClient.post('/auth/logout')
    } catch (error) {
      // Ignore errors on logout
    }

    localStorage.removeItem('ctfd_user')
    return { success: true }
  }

  async forgotPassword(email: string): Promise<{ success: boolean; message?: string; errors?: string[] }> {
    return dojoApiClient.post<{ success: boolean; message?: string; errors?: string[] }>('/auth/forgot-password', { email })
  }

  async resetPassword(token: string, password: string): Promise<{ success: boolean; message?: string }> {
    return dojoApiClient.post<{ success: boolean; message?: string }>(`/auth/reset-password/${token}`, { password })
  }

  async verifyEmail(token: string): Promise<{ success: boolean; message?: string }> {
    return dojoApiClient.get<{ success: boolean; message?: string }>(`/auth/verify/${token}`)
  }

  isAuthenticated(): boolean {
    return !!localStorage.getItem('ctfd_user')
  }

  getCurrentUser() {
    if (!this.isAuthenticated()) {
      return null
    }

    try {
      const userData = localStorage.getItem('ctfd_user')
      if (userData) {
        return JSON.parse(userData)
      }
      return null
    } catch (error) {
      // If parsing fails, clear the invalid data
      localStorage.removeItem('ctfd_user')
      return null
    }
  }

  async fetchCurrentUser(): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const response = await dojoApiClient.get<any>('/users/me')

      if (response && response.id) {
        localStorage.setItem('ctfd_user', JSON.stringify(response))
        return { success: true, data: response }
      } else {
        localStorage.removeItem('ctfd_user')
        return { success: false, error: 'User not authenticated' }
      }
    } catch (error) {
      if (error instanceof Error && 'status' in error && (error as any).status === 401) {
        localStorage.removeItem('ctfd_user')
      }
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to fetch user'
      }
    }
  }

  async updateProfile(data: any): Promise<{ success: boolean; user?: any }> {
    const response = await dojoApiClient.patch<{ success: boolean; user?: any }>('/users/me', data)
    if (response.success && response.user) {
      localStorage.setItem('ctfd_user', JSON.stringify(response.user))
    }
    return response
  }

  async changePassword(data: ChangePasswordData): Promise<{ success: boolean; message?: string }> {
    return dojoApiClient.post<{ success: boolean; message?: string }>('/users/me/password', data)
  }

  async confirmResetPassword(token: string, password: string): Promise<{ success: boolean; message?: string }> {
    return dojoApiClient.post<{ success: boolean; message?: string }>(`/auth/reset/${token}`, { password })
  }

  async resendVerification(): Promise<{ success: boolean; message?: string }> {
    return dojoApiClient.post<{ success: boolean; message?: string }>('/auth/resend-verification', {})
  }
}

export const authService = new AuthService()
