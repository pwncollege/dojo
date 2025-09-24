import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { SmartFlagInput } from '@/components/challenge/SmartFlagInput'
import { NextChallengeButton } from '@/components/challenge/NextChallengeButton'
import { useAnimations } from '@/stores'
import {
  Terminal,
  Code,
  Monitor,
  Maximize2,
  Minimize2,
  ChevronLeft,
  Video,
  FileText,
  Play,
  Presentation,
  FileVideo,
  X,
  ChevronRight
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useState, useEffect } from 'react'

interface Resource {
  id: string
  name: string
  type: 'markdown' | 'lecture' | 'header'
  content?: string
  video?: string
  playlist?: string
  slides?: string
}

interface AnimatedWorkspaceHeaderProps {
  // Challenge mode props
  activeChallenge: {
    dojoId: string
    moduleId: string
    challengeId: string
    name: string
  }
  dojoName: string
  moduleName: string
  activeService: string
  workspaceActive: boolean

  // Resource mode props
  activeResource?: Resource | null
  activeResourceTab?: string
  onResourceTabChange?: (tab: string) => void

  // Common props
  isFullScreen: boolean
  headerHidden: boolean
  onServiceChange: (service: string) => void
  onFullScreenToggle: () => void
  onClose?: () => void
  onResourceClose?: () => void
}

export function AnimatedWorkspaceHeader({
  activeChallenge,
  dojoName,
  moduleName,
  activeService,
  workspaceActive,
  activeResource,
  activeResourceTab,
  onResourceTabChange,
  isFullScreen,
  headerHidden,
  onServiceChange,
  onFullScreenToggle,
  onClose,
  onResourceClose
}: AnimatedWorkspaceHeaderProps) {
  const animations = useAnimations()

  if (headerHidden) {
    return null
  }

  // Persist workspace active state to prevent tabs from disappearing during service switches
  const [persistentWorkspaceActive, setPersistentWorkspaceActive] = useState(workspaceActive)

  useEffect(() => {
    if (workspaceActive) {
      setPersistentWorkspaceActive(true)
    }
    // Only set to false after a delay to prevent flickering
    if (!workspaceActive) {
      const timeout = setTimeout(() => {
        setPersistentWorkspaceActive(false)
      }, animations.medium * 1000) // Use animation duration for consistency
      return () => clearTimeout(timeout)
    }
  }, [workspaceActive])

  const isResourceMode = !!activeResource && activeResource.type !== "header"
  const hasVideo = activeResource?.type === "lecture" && activeResource.video
  const hasSlides = activeResource?.type === "lecture" && activeResource.slides
  const isMarkdown = activeResource?.type === "markdown"

  return (
    <div className="border-b bg-background backdrop-blur-md shadow-sm">
      <div className="px-6 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            {/* Back button */}
            <Button
              variant="ghost"
              size="icon"
              onClick={onClose}
              className="hover:bg-primary/10 hover:text-primary h-8 w-8 transition-colors"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>

            <div className="flex items-center gap-3">
              {/* Animated icon */}
              <motion.div
                className="p-1.5 rounded-lg bg-primary/10"
                layout
                transition={{ duration: animations.medium, ease: [0.25, 0.46, 0.45, 0.94] }}
              >
                <AnimatePresence mode="wait">
                  {isResourceMode ? (
                    <motion.div
                      key="resource-icon"
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.8 }}
                      transition={{ duration: animations.medium }}
                    >
                      {activeResource.type === "lecture" ? (
                        <Video className="h-4 w-4 text-primary" />
                      ) : (
                        <FileText className="h-4 w-4 text-primary" />
                      )}
                    </motion.div>
                  ) : (
                    <motion.div
                      key="challenge-icon"
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.8 }}
                      transition={{ duration: animations.medium }}
                    >
                      <Terminal className="h-4 w-4 text-primary" />
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>

              <div>
                {/* Animated title */}
                <AnimatePresence mode="wait">
                  <motion.h1
                    key={isResourceMode ? `resource-${activeResource.id}` : `challenge-${activeChallenge.challengeId}`}
                    className="text-lg font-semibold leading-tight"
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 20 }}
                    transition={{ duration: animations.medium, ease: [0.25, 0.46, 0.45, 0.94] }}
                  >
                    {isResourceMode ? activeResource.name : activeChallenge.name}
                  </motion.h1>
                </AnimatePresence>

                {/* Animated subtitle */}
                <motion.div
                  className="flex items-center gap-3 mt-0.5"
                  layout
                  transition={{ duration: animations.medium, ease: [0.25, 0.46, 0.45, 0.94] }}
                >
                  <AnimatePresence mode="wait">
                    {isResourceMode ? (
                      <motion.div
                        key="resource-info"
                        className="flex items-center gap-3"
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                        transition={{ duration: animations.medium }}
                      >
                        {hasVideo && (
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <FileVideo className="h-3 w-3" />
                            <span>Video</span>
                          </div>
                        )}
                        {hasSlides && (
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <Presentation className="h-3 w-3" />
                            <span>Slides</span>
                          </div>
                        )}
                        {isMarkdown && (
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <FileText className="h-3 w-3" />
                            <span>Reading</span>
                          </div>
                        )}
                      </motion.div>
                    ) : (
                      <motion.div
                        key="challenge-info"
                        className="flex items-center gap-1.5 text-xs text-muted-foreground"
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                        transition={{ duration: animations.medium }}
                      >
                        <span>{dojoName} → {moduleName}</span>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.div>
              </div>
            </div>
          </div>

          {/* Right side: Context-specific controls */}
          <div className="flex items-center gap-3">
            <AnimatePresence mode="wait">
              {!isResourceMode && (
                <motion.div
                  key="challenge-controls"
                  className="flex items-center gap-3"
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ duration: animations.medium, ease: [0.25, 0.46, 0.45, 0.94] }}
                >
                  {/* Smart Flag Input */}
                  <SmartFlagInput
                    dojoId={activeChallenge.dojoId}
                    moduleId={activeChallenge.moduleId}
                    challengeId={activeChallenge.challengeId}
                  />

                  {/* Next Challenge Button */}
                  <NextChallengeButton />

                  {/* Service Tabs */}
                  {persistentWorkspaceActive && (
                    <Tabs value={activeService} onValueChange={onServiceChange}>
                      <TabsList className="bg-muted/50 h-9 p-1">
                        <TabsTrigger value="terminal" className="gap-1.5 h-7 px-3 text-xs cursor-pointer transition-all duration-200 data-[state=active]:bg-background data-[state=active]:shadow-sm">
                          <Terminal className="h-3 w-3" />
                          Terminal
                        </TabsTrigger>
                        <TabsTrigger value="code" className="gap-1.5 h-7 px-3 text-xs cursor-pointer transition-all duration-200 data-[state=active]:bg-background data-[state=active]:shadow-sm">
                          <Code className="h-3 w-3" />
                          Editor
                        </TabsTrigger>
                        <TabsTrigger value="desktop" className="gap-1.5 h-7 px-3 text-xs cursor-pointer transition-all duration-200 data-[state=active]:bg-background data-[state=active]:shadow-sm">
                          <Monitor className="h-3 w-3" />
                          Desktop
                        </TabsTrigger>
                      </TabsList>
                    </Tabs>
                  )}
                </motion.div>
              )}

              {isResourceMode && ((hasVideo && hasSlides) || (hasVideo && isMarkdown) || (hasSlides && isMarkdown)) && (
                <motion.div
                  key="resource-controls"
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ duration: animations.medium, ease: [0.25, 0.46, 0.45, 0.94] }}
                >
                  <Tabs value={activeResourceTab || "video"} onValueChange={onResourceTabChange}>
                    <TabsList className="bg-muted/50 h-9 p-1">
                      {hasVideo && (
                        <TabsTrigger value="video" className="gap-1.5 h-7 px-3 text-xs cursor-pointer transition-all duration-200 data-[state=active]:bg-background data-[state=active]:shadow-sm">
                          <Play className="h-3 w-3" />
                          Video
                        </TabsTrigger>
                      )}
                      {hasSlides && (
                        <TabsTrigger value="slides" className="gap-1.5 h-7 px-3 text-xs cursor-pointer transition-all duration-200 data-[state=active]:bg-background data-[state=active]:shadow-sm">
                          <Presentation className="h-3 w-3" />
                          Slides
                        </TabsTrigger>
                      )}
                      {isMarkdown && activeResource?.content && (
                        <TabsTrigger value="reading" className="gap-1.5 h-7 px-3 text-xs cursor-pointer transition-all duration-200 data-[state=active]:bg-background data-[state=active]:shadow-sm">
                          <FileText className="h-3 w-3" />
                          Reading
                        </TabsTrigger>
                      )}
                    </TabsList>
                  </Tabs>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Common controls */}
            <motion.div
              className="flex items-center gap-1"
              layout
              transition={{ duration: animations.medium, ease: [0.25, 0.46, 0.45, 0.94] }}
            >
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={onFullScreenToggle}
                    className="hover:bg-primary/10 hover:text-primary h-8 w-8 transition-colors"
                  >
                    {isFullScreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p>{isFullScreen ? "Exit fullscreen" : "Enter fullscreen"}</p>
                </TooltipContent>
              </Tooltip>

              {isResourceMode && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onClose}
                  className="hover:bg-destructive/10 hover:text-destructive h-8 w-8 transition-colors"
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              )}
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  )
}