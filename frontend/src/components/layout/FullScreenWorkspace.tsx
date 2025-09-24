import { FlagSubmission } from '@/components/challenge/FlagSubmission'

interface FullScreenWorkspaceProps {
  activeChallenge: {
    dojoId: string
    moduleId: string
    challengeId: string
    name: string
  }
  activeService: string
  workspaceStatus?: { active: boolean }
  workspaceData?: { iframe_src?: string }
}

export function FullScreenWorkspace({
  activeChallenge,
  activeService,
  workspaceStatus,
  workspaceData
}: FullScreenWorkspaceProps) {
  return (
    <div className="w-full h-screen">
      {activeService === 'flag' ? (
        <div className="flex items-center justify-center h-full">
          <FlagSubmission
            dojoId={activeChallenge.dojoId}
            moduleId={activeChallenge.moduleId}
            challengeId={activeChallenge.challengeId}
            challengeName={activeChallenge.name}
          />
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