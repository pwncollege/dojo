'use client'

import { HeaderProvider } from '@/contexts/HeaderContext'
import { ActiveChallengeWidget } from '@/components/workspace/ActiveChallengeWidget'
import { useUIStore } from '@/stores'
import { workspaceService } from '@/services/workspace'

interface WorkspaceProviderProps {
  children: React.ReactNode
}

export function WorkspaceProvider({ children }: WorkspaceProviderProps) {
  const activeChallenge = useUIStore(state => state.activeChallenge)
  const setActiveChallenge = useUIStore(state => state.setActiveChallenge)

  const handleKillChallenge = async () => {
    try {
      const result = await workspaceService.terminateWorkspace()

      if (result.success) {
        console.log('Workspace terminated successfully')
        setActiveChallenge(null)
      } else {
        console.error('Failed to terminate workspace:', result.error)
      }
    } catch (error) {
      console.error('Failed to terminate workspace:', error)
      setActiveChallenge(null)
    }
  }

  return (
    <HeaderProvider>
      {children}
      <ActiveChallengeWidget
        activeChallenge={activeChallenge}
        onKillChallenge={handleKillChallenge}
      />
    </HeaderProvider>
  )
}