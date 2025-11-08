'use client'

import { useEffect } from 'react'
import { usePathname } from 'next/navigation'
import { useUIStore, useAuthStore, useWorkspaceStore } from '@/stores'
import { workspaceService } from '@/services/workspace'
import { ActiveChallengeWidget } from '@/components/workspace/ActiveChallengeWidget'

interface ActiveChallengeProviderProps {
  children: React.ReactNode
}

export function ActiveChallengeProvider({ children }: ActiveChallengeProviderProps) {
  const pathname = usePathname()
  const activeChallenge = useWorkspaceStore(state => state.activeChallenge)
  const setActiveChallenge = useWorkspaceStore(state => state.setActiveChallenge)
  const isAuthenticated = useAuthStore(state => state.isAuthenticated)
  const user = useAuthStore(state => state.user)
  const authError = useAuthStore(state => state.authError)


  // Fetch active challenge from server on page load/refresh - only if authenticated
  useEffect(() => {
    if (!isAuthenticated) {
      setActiveChallenge(null)
      return
    }

    const fetchActiveChallenge = async () => {
      try {
        const response = await workspaceService.getCurrentChallenge()

        if (response.current_challenge) {
          const challenge = response.current_challenge

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
          setActiveChallenge(null)
        }
      } catch (error) {
        console.error('ActiveChallengeProvider: Failed to fetch active challenge:', error)
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

  return (
    <>
      {children}

      {/* Active Challenge Widget - shows when there's an active challenge and we're not on the challenge page */}
      <ActiveChallengeWidget
        activeChallenge={activeChallenge}
        onKillChallenge={handleKillChallenge}
      />
    </>
  )
}
