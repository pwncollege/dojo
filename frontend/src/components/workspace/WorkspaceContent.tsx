import { motion } from 'framer-motion'
import { ResourceViewer } from './ResourceViewer'
import { WorkspaceServiceViewer } from './WorkspaceServiceViewer'

interface Resource {
  id: string
  name: string
  type: 'markdown' | 'lecture' | 'header'
  content?: string
  video?: string
  playlist?: string
  slides?: string
}

interface WorkspaceContentProps {
  workspaceActive: boolean
  workspaceData: any
  activeService: string
  activeResource?: Resource | null
  activeResourceTab?: string
  activeChallenge: {
    dojoId: string
    moduleId: string
    challengeId: string
    name: string
  }
  dojoName: string
  moduleName: string
  isStarting?: boolean
  onResourceClose?: () => void
  onChallengeClose?: () => void
  onServiceChange?: (service: string) => void
  onResourceTabChange?: (tab: string) => void
}

export function WorkspaceContent({
  workspaceActive,
  workspaceData,
  activeService,
  activeResource,
  activeResourceTab,
  activeChallenge,
  dojoName,
  moduleName,
  isStarting = false,
  onResourceClose,
  onChallengeClose,
  onServiceChange,
  onResourceTabChange
}: WorkspaceContentProps) {
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
          activeTab={activeResourceTab}
          onTabChange={onResourceTabChange}
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
        activeService={activeService}
        isStarting={isStarting}
        className="h-full"
      />
    </motion.div>
  )
}
