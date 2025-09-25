import { FlagSubmission } from '@/components/challenge/FlagSubmission'
import { useWorkspaceStore } from '@/stores'

interface FullScreenWorkspaceProps {
  workspaceStatus?: { active: boolean }
  workspaceData?: { iframe_src?: string }
}

export function FullScreenWorkspace({
  workspaceStatus,
  workspaceData
}: FullScreenWorkspaceProps) {
  // Get state from workspace store
  const activeChallenge = useWorkspaceStore(state => state.activeChallenge)
  const activeService = useWorkspaceStore(state => state.activeService)
  return (
    <div className="w-full h-screen">
      {activeService === 'flag' ? (
        <div className="flex items-center justify-center h-full">
          {activeChallenge && (
            <FlagSubmission
              dojoId={activeChallenge.dojoId}
              moduleId={activeChallenge.moduleId}
              challengeId={activeChallenge.challengeId}
              challengeName={activeChallenge.challengeName}
            />
          )}
        </div>
      ) : workspaceStatus?.active && workspaceData?.iframe_src ? (
        <iframe
          src={workspaceData.iframe_src.startsWith('/')
            ? `http://localhost${workspaceData.iframe_src}`
            : workspaceData.iframe_src}
          className="w-full h-full border-0"
          title={`Workspace ${activeService}`}
        />
      ) : (
        <div className="flex items-center justify-center h-full text-muted-foreground">
          <div className="text-center">
            <div className="w-16 h-16 border-4 border-muted border-t-primary rounded-full animate-spin mx-auto mb-4" />
            <p>Preparing your workspace...</p>
            <p className="text-sm mt-2">This may take a few moments.</p>
          </div>
        </div>
      )}
    </div>
  )
}