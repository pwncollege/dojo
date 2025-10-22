import React, { createContext, useContext, useState, useEffect } from 'react'
import { authService } from '@/services/auth'

interface User {
  user_id: number
  username: string
  email: string
  type: string
  verified: boolean
  team_id?: number
}

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (credentials: { name: string; password: string; remember_me?: boolean }) => Promise<void>
  logout: () => void
  refreshUser: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const isAuthenticated = !!user && authService.isAuthenticated()

  const login = async (credentials: { name: string; password: string; remember_me?: boolean }) => {
    setIsLoading(true)
    try {
      const response = await authService.login(credentials)
      if (response.success && response.data) {
        setUser({
          user_id: response.data.user_id,
          username: response.data.username,
          email: response.data.email,
          type: response.data.type,
          verified: response.data.verified,
          team_id: response.data.team_id
        })
      } else {
        throw new Error(response.errors?.join(', ') || 'Login failed')
      }
    } finally {
      setIsLoading(false)
    }
  }

  const logout = () => {
    authService.logout()
    setUser(null)
  }

  const refreshUser = () => {
    const currentUser = authService.getCurrentUser()
    if (currentUser) {
      setUser(currentUser)
    } else {
      setUser(null)
    }
  }

  // Check for existing auth on mount
  useEffect(() => {
    if (authService.isAuthenticated()) {
      const currentUser = authService.getCurrentUser()
      if (currentUser) {
        setUser(currentUser)
      }
    }
    setIsLoading(false)
  }, [])

  const value: AuthContextType = {
    user,
    isAuthenticated,
    isLoading,
    login,
    logout,
    refreshUser
  }

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

export default AuthContext