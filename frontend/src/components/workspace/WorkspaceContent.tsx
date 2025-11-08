import { motion } from 'framer-motion'
import { ResourceViewer } from './ResourceViewer'
import { WorkspaceServiceViewer } from './WorkspaceServiceViewer'
import { useWorkspaceStore } from '@/stores'
import { useResourceTab } from '@/components/layout/DojoWorkspaceLayout'
import type { Resource } from '@/types/api'

interface WorkspaceContentProps {
  workspaceActive: boolean
  workspaceData: any
  activeResource?: Resource | null
  onResourceClose?: () => void
}

export function WorkspaceContent({
  workspaceActive,
  workspaceData,
  activeResource,
  onResourceClose
}: WorkspaceContentProps) {
  // Get state from workspace store
  const activeService = useWorkspaceStore(state => state.activeService)
  const activeChallenge = useWorkspaceStore(state => state.activeChallenge)
  const isStarting = activeChallenge?.isStarting || false
  // Show resource viewer if a resource is selected (but ignore header type resources)
  if (activeResource && activeResource.type !== "header") {
    return (
      <motion.div
        className="flex-1"
        initial={{ opacity: 0, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.98 }}
        transition={{
          duration: 0.3,
          ease: [0.25, 0.46, 0.45, 0.94]
        }}
      >
        <ResourceViewer
          resource={activeResource}
          activeTab={useResourceTab()?.activeResourceTab}
          onClose={onResourceClose}
          className="h-full"
        />
      </motion.div>
    )
  }

  // Show workspace service viewer for challenges
  return (
    <motion.div
      className="flex-1"
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{
        duration: 0.3,
        ease: [0.25, 0.46, 0.45, 0.94]
      }}
    >
      <WorkspaceServiceViewer
        workspaceActive={workspaceActive}
        workspaceData={workspaceData}
        className="h-full"
      />
    </motion.div>
  )
}
