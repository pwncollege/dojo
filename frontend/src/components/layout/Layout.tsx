'use client'

import { useEffect } from 'react'
import { usePathname } from 'next/navigation'
import { Header } from './Header'
import { HeaderProvider } from '@/contexts/HeaderContext'
import { ActiveChallengeWidget } from '@/components/workspace/ActiveChallengeWidget'
import { useUIStore, useAuthStore } from '@/stores'
import { workspaceService } from '@/services/workspace'

interface LayoutProps {
  children: React.ReactNode
}

export function Layout({ children }: LayoutProps) {
  const pathname = usePathname()
  const activeChallenge = useUIStore(state => state.activeChallenge)
  const setActiveChallenge = useUIStore(state => state.setActiveChallenge)
  const isAuthenticated = useAuthStore(state => state.isAuthenticated)
  const user = useAuthStore(state => state.user)
  const authError = useAuthStore(state => state.authError)

  // Debug auth state changes
  console.log('Layout render - Auth state:', {
    isAuthenticated,
    user,
    authError,
    hasActiveChallenge: !!activeChallenge,
    pathname
  })

  // Fetch active challenge from server on page load/refresh - only if authenticated
  useEffect(() => {
    console.log('Layout: Auth state check:', {
      isAuthenticated,
      localStorage_ctfd_user: !!localStorage.getItem('ctfd_user')
    })

    if (!isAuthenticated) {
      console.log('Layout: Not authenticated, clearing active challenge')
      setActiveChallenge(null)
      return
    }

    const fetchActiveChallenge = async () => {
      try {
        console.log('Layout: Fetching active challenge from server...')
        const response = await workspaceService.getCurrentChallenge()
        console.log('Layout: Active challenge response:', response)

        if (response.current_challenge) {
          const challenge = response.current_challenge
          console.log('Layout: Setting active challenge:', challenge)

          setActiveChallenge({
            dojoId: challenge.dojo_id,
            moduleId: challenge.module_id,
            challengeId: challenge.challenge_id,
            challengeName: challenge.challenge_name || challenge.challenge_id, // Fallback to ID if name not provided
            dojoName: challenge.dojo_id, // API doesn't provide dojo name, use ID
            moduleName: challenge.module_id, // API doesn't provide module name, use ID
            isStarting: false
          })
        } else {
          console.log('Layout: No active challenge from server, clearing state')
          setActiveChallenge(null)
        }
      } catch (error) {
        console.error('Layout: Failed to fetch active challenge:', error)
        // Don't clear active challenge on error - keep existing state
      }
    }

    fetchActiveChallenge()
  }, [isAuthenticated, setActiveChallenge]) // Depend on proper auth state

  const handleKillChallenge = async () => {
    try {
      // Call the workspace termination API
      const result = await workspaceService.terminateWorkspace()

      if (result.success) {
        console.log('Workspace terminated successfully')
        setActiveChallenge(null)
      } else {
        console.error('Failed to terminate workspace:', result.error)
      }
    } catch (error) {
      console.error('Failed to terminate workspace:', error)
      // Still clear the active challenge state even if the API call fails
      setActiveChallenge(null)
    }
  }

  // Check if we should show header
  const isWorkspacePage = pathname.includes('/workspace/')
  const isAuthPage = pathname.startsWith('/login') || pathname.startsWith('/register') || pathname.startsWith('/forgot-password')
  const showHeader = !isWorkspacePage && !isAuthPage

  return (
    <HeaderProvider>
      <div className="min-h-screen bg-background">
        {showHeader && <Header />}
        <main>{children}</main>

        {/* Active Challenge Widget - shows when there's an active challenge and we're not on the challenge page */}
        <ActiveChallengeWidget
          activeChallenge={activeChallenge}
          onKillChallenge={handleKillChallenge}
        />
      </div>
    </HeaderProvider>
  )
}