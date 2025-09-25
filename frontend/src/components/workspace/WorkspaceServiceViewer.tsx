import { motion } from 'framer-motion'
import { WorkspaceService } from './WorkspaceService'
import { useWorkspaceStore } from '@/stores'

interface WorkspaceServiceViewerProps {
  workspaceActive: boolean
  workspaceData: any
  loadingMessage?: string
  className?: string
}

export function WorkspaceServiceViewer({
  workspaceActive,
  workspaceData,
  loadingMessage,
  className
}: WorkspaceServiceViewerProps) {
  // Get state from workspace store
  const activeService = useWorkspaceStore(state => state.activeService)
  const activeChallenge = useWorkspaceStore(state => state.activeChallenge)
  const isStarting = activeChallenge?.isStarting || false
  const iframeSrc = workspaceData?.iframe_src

  return (
    <motion.div
      className={`h-full ${activeService === 'terminal' ? 'p-4' : ''}`}
      style={{
        backgroundColor: activeService === 'terminal' ? 'var(--service-bg)' : undefined
      }}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.3,
        delay: 0.2, // Delay to start after workspace page animation
        ease: [0.25, 0.46, 0.45, 0.94]
      }}
    >
      {isStarting ? (
        <div className="flex items-center justify-center h-full text-muted-foreground" style={{ backgroundColor: activeService === 'terminal' ? 'var(--service-bg)' : undefined }}>
          <div className="text-center">
            <div className="w-16 h-16 border-4 border-muted border-t-primary rounded-full animate-spin mx-auto mb-4" />
            <p className="text-lg font-medium">Starting next challenge...</p>
            <p className="text-sm text-muted-foreground mt-2">Starting challenge environment</p>
          </div>
        </div>
      ) : workspaceActive && iframeSrc ? (
        <WorkspaceService
          iframeSrc={iframeSrc}
        />
      ) : (
        <div className="flex items-center justify-center h-full text-muted-foreground" style={{ backgroundColor: activeService === 'terminal' ? 'var(--service-bg)' : undefined }}>
          <div className="text-center">
            <div className="w-16 h-16 border-4 border-muted border-t-primary rounded-full animate-spin mx-auto mb-4" />
            <p>Preparing your workspace...</p>
            <p className="text-sm mt-2">This may take a few moments.</p>
          </div>
        </div>
      )}
    </motion.div>
  )
}
