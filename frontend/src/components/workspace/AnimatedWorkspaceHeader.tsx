import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { SmartFlagInput } from '@/components/challenge/SmartFlagInput'
import { NextChallengeButton } from '@/components/challenge/NextChallengeButton'
import { useAnimations, useWorkspaceStore } from '@/stores'
import { useStartChallenge } from '@/hooks/useDojo'
import { workspaceService } from '@/services/workspace'
import {
  Terminal,
  Code,
  Monitor,
  Maximize2,
  Minimize2,
  Video,
  FileText,
  Play,
  Presentation,
  FileVideo,
  X,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Shield,
  Info,
  MoreVertical
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import type { Resource } from '@/types/api'
import { useResourceTab } from '@/components/layout/DojoWorkspaceLayout'

interface AnimatedWorkspaceHeaderProps {
  // Required props from parent that aren't in store
  dojoName: string
  moduleName: string
  workspaceActive: boolean

  // Resource mode props
  activeResource?: Resource | null

  // Callbacks
  onClose?: () => void
  onResourceClose?: () => void
}

export function AnimatedWorkspaceHeader({
  dojoName,
  moduleName,
  workspaceActive,
  activeResource,
  onClose,
  onResourceClose
}: AnimatedWorkspaceHeaderProps) {
  const animations = useAnimations()

  // Get state from workspace store
  const activeChallenge = useWorkspaceStore(state => state.activeChallenge)
  const activeService = useWorkspaceStore(state => state.activeService)
  const isFullScreen = useWorkspaceStore(state => state.isFullScreen)
  const headerHidden = useWorkspaceStore(state => state.headerHidden)

  // Get actions from workspace store
  const setActiveService = useWorkspaceStore(state => state.setActiveService)
  const setFullScreen = useWorkspaceStore(state => state.setFullScreen)
  const setActiveChallenge = useWorkspaceStore(state => state.setActiveChallenge)

  // Get resource tab state from context
  const resourceTabContext = useResourceTab()
  const activeResourceTab = resourceTabContext?.activeResourceTab || "video"
  const setActiveResourceTab = resourceTabContext?.setActiveResourceTab

  // Restart functionality
  const [practiceMode, setPracticeMode] = useState(false)
  const [nextLoading, setNextLoading] = useState(false)
  const startChallenge = useStartChallenge()
  const router = useRouter()

  const handleRestartChallenge = async () => {
    if (!activeChallenge) return

    try {
      await startChallenge.mutateAsync({
        dojoId: activeChallenge.dojoId,
        moduleId: activeChallenge.moduleId,
        challengeId: activeChallenge.challengeId,
        practice: practiceMode
      })
    } catch (error) {
      console.error('Failed to restart challenge:', error)
    }
  }

  const handleNextChallenge = async () => {
    try {
      setNextLoading(true)

      const response = await workspaceService.getNextChallenge()

      if (response.success && response.dojo && response.module && response.challenge) {
        const nextUrl = `/dojo/${response.dojo}/module/${response.module}/workspace/challenge/${response.challenge}`

        // Check if we're switching to a different module
        if (activeChallenge && activeChallenge.moduleId !== response.module) {
          // Different module - need full navigation to load new module data
          router.push(nextUrl)
        } else {
          // Same module - can do client-side transition
          setActiveChallenge({
            dojoId: response.dojo,
            moduleId: response.module,
            challengeId: response.challenge,
            challengeName: 'Next Challenge',
            dojoName: '',
            moduleName: '',
            isStarting: true
          })

          // Update URL without triggering full navigation
          window.history.replaceState(null, '', nextUrl)

          startChallenge.mutateAsync({
            dojoId: response.dojo,
            moduleId: response.module,
            challengeId: response.challenge
          }).catch(error => {
            console.error('Failed to start challenge:', error)
          })
        }
      } else {
        // No next challenge available
      }
    } catch (error) {
      console.error('Failed to get next challenge:', error)
    } finally {
      setNextLoading(false)
    }
  }

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

              <motion.div
                layout
                transition={{ duration: animations.medium, ease: [0.25, 0.46, 0.45, 0.94] }}
              >
                {/* Animated title */}
                <AnimatePresence mode="wait">
                  <motion.h1
                    key={isResourceMode ? `resource-${activeResource.id}` : `challenge-${activeChallenge?.challengeId}`}
                    className="text-lg font-semibold leading-tight"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: animations.fast }}
                  >
                    {isResourceMode ? activeResource.name : activeChallenge?.challengeName}
                  </motion.h1>
                </AnimatePresence>

                {/* Subtitle */}
                <div className="flex items-center gap-3 mt-0.5">
                  <AnimatePresence mode="wait">
                    {isResourceMode ? (
                      <motion.div
                        key="resource-info"
                        className="flex items-center gap-3"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: animations.fast }}
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
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: animations.fast }}
                      >
                        <span>{dojoName} → {moduleName}</span>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </motion.div>
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
                  {activeChallenge && (
                    <SmartFlagInput
                      dojoId={activeChallenge.dojoId}
                      moduleId={activeChallenge.moduleId}
                      challengeId={activeChallenge.challengeId}
                    />
                  )}

                  {/* Service Tabs */}
                  {persistentWorkspaceActive && (
                    <Tabs value={activeService} onValueChange={setActiveService}>
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
                  <Tabs value={activeResourceTab} onValueChange={setActiveResourceTab || (() => {})}>
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
              {/* Challenge Actions Dropdown */}
              {!isResourceMode && activeChallenge && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="hover:bg-primary/10 hover:text-primary h-8 w-8 transition-colors"
                    >
                      <MoreVertical className="h-3.5 w-3.5" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-56">
                    {/* Practice Mode Toggle */}
                    <div className="px-2 py-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Shield className={`h-4 w-4 ${practiceMode ? 'text-primary' : 'text-muted-foreground'}`} />
                          <span className="text-sm font-medium">Practice Mode</span>
                        </div>
                        <Switch
                          checked={practiceMode}
                          onCheckedChange={async (checked) => {
                            setPracticeMode(checked)
                            // Auto-restart challenge when practice mode changes
                            if (activeChallenge) {
                              try {
                                await startChallenge.mutateAsync({
                                  dojoId: activeChallenge.dojoId,
                                  moduleId: activeChallenge.moduleId,
                                  challengeId: activeChallenge.challengeId,
                                  practice: checked
                                })
                              } catch (error) {
                                console.error('Failed to restart challenge:', error)
                              }
                            }
                          }}
                          className="h-4 w-8"
                        />
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">
                        Privileged access, flags don't count
                      </p>
                    </div>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={handleRestartChallenge}
                      disabled={startChallenge.isPending}
                      className="cursor-pointer"
                    >
                      <RefreshCw className="h-4 w-4 mr-2" />
                      Restart challenge
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={handleNextChallenge}
                      disabled={nextLoading || startChallenge.isPending}
                      className="cursor-pointer"
                    >
                      {nextLoading ? (
                        <div className="w-4 h-4 mr-2 border-2 border-current border-t-transparent rounded-full animate-spin" />
                      ) : (
                        <ChevronRight className="h-4 w-4 mr-2" />
                      )}
                      Next challenge
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}

              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setFullScreen(!isFullScreen)}
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
