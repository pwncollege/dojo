import { useState, useEffect, useRef, useMemo } from 'react'
import { motion } from 'framer-motion'
import { usePathname } from 'next/navigation'
import { useWorkspace } from '@/hooks/useWorkspace'
import { useStartChallenge } from '@/hooks/useDojo'
import { FullScreenWorkspace } from './FullScreenWorkspace'
import { useUIStore } from '@/stores'
import { CommandPalette } from '@/components/ui/command-palette'
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'
import { useCommands } from '@/hooks/useCommands'
import { useHotkeys, hotkey } from '@/hooks/useHotkeys'
import { WorkspaceSidebar } from '@/components/workspace/WorkspaceSidebar'
import { AnimatedWorkspaceHeader } from '@/components/workspace/AnimatedWorkspaceHeader'
import { WorkspaceContent } from '@/components/workspace/WorkspaceContent'
import type { Dojo, DojoModule } from '@/types/api'
import { useTheme } from '@/components/theme/ThemeProvider'

interface DojoWorkspaceLayoutProps {
  dojo: Dojo
  modules: DojoModule[]
  onChallengeStart: (dojoId: string, moduleId: string, challengeId: string) => void
  onChallengeClose: () => void
  onResourceSelect?: (resourceId: string | null) => void
}

export function DojoWorkspaceLayout({
  dojo,
  modules,
  onChallengeStart,
  onChallengeClose,
  onResourceSelect
}: DojoWorkspaceLayoutProps) {
  // ALL HOOKS MUST BE AT THE TOP - before any conditional returns
  // Use workspace state from Zustand store with individual selectors to avoid infinite loops
  const activeService = useUIStore(state => state.workspaceState.activeService)
  const preferredService = useUIStore(state => state.workspaceState.preferredService)
  const sidebarCollapsed = useUIStore(state => state.workspaceState.sidebarCollapsed)
  const isFullScreen = useUIStore(state => state.workspaceState.isFullScreen)
  const sidebarWidth = useUIStore(state => state.workspaceState.sidebarWidth)
  const commandPaletteOpen = useUIStore(state => state.workspaceState.commandPaletteOpen)
  const workspaceHeaderHidden = useUIStore(state => state.workspaceState.workspaceHeaderHidden)

  const setActiveService = useUIStore(state => state.setActiveService)
  const setSidebarCollapsed = useUIStore(state => state.setSidebarCollapsed)
  const setFullScreen = useUIStore(state => state.setFullScreen)
  const setSidebarWidth = useUIStore(state => state.setSidebarWidth)
  const setCommandPaletteOpen = useUIStore(state => state.setCommandPaletteOpen)
  const setWorkspaceHeaderHidden = useUIStore(state => state.setWorkspaceHeaderHidden)
  const setActiveChallenge = useUIStore(state => state.setActiveChallenge)

  const [activeResourceTab, setActiveResourceTab] = useState<string>("video")
  const startChallengeMutation = useStartChallenge()
  const { palette } = useTheme()
  const pathname = usePathname()

  // Parse URL to determine active challenge/resource
  const urlParts = pathname.split('/')
  const workspaceIndex = urlParts.indexOf('workspace')
  const type = urlParts[workspaceIndex + 1] // 'challenge' or 'resource'
  const id = urlParts[workspaceIndex + 2] // challengeId or resourceId

  const challengeId = type === 'challenge' ? id : undefined
  const resourceId = type === 'resource' ? id : undefined
  const isResourceMode = !!resourceId
  const isChallenge = !!challengeId


  // Get the current module (we only have one in workspace view)
  const currentModule = modules[0]

  // Find active challenge/resource
  const challenge = currentModule?.challenges?.find(c => c.id === challengeId)
  const resource = currentModule?.resources?.find(r => r.id === resourceId)

  // Create activeChallenge object for consistency
  const activeChallenge = isChallenge && challenge ? {
    dojoId: dojo.id,
    moduleId: currentModule.id,
    challengeId: challenge.id,
    name: challenge.name
  } : isResourceMode && resource ? {
    dojoId: dojo.id,
    moduleId: currentModule.id,
    challengeId: 'resource',
    name: resource.name
  } : undefined

  // Pass theme name for terminal and code services
  const serviceTheme = (activeService === 'terminal' || activeService === 'code') ? palette : undefined

  // Single workspace call that gets status and data in one request
  // Only enable when we have an active challenge AND it's not currently starting
  // Include challenge info in query key so it refetches when challenge changes
  const { data: workspaceData } = useWorkspace(
    {
      service: activeService,
      challenge: activeChallenge ? `${activeChallenge.dojoId}-${activeChallenge.moduleId}-${activeChallenge.challengeId}` : '',
      theme: serviceTheme
    },
    !!activeChallenge
  )

  // Set active challenge in UI store for widget
  useEffect(() => {
    if (activeChallenge) {
      setActiveChallenge({
        dojoId: activeChallenge.dojoId,
        moduleId: activeChallenge.moduleId,
        challengeId: activeChallenge.challengeId,
        challengeName: activeChallenge.name,
        dojoName: dojo.name,
        moduleName: currentModule.name
      })
    }
  }, [activeChallenge, dojo.name, currentModule?.name, setActiveChallenge])

  // Handler function for challenge start
  const handleChallengeStart = async (moduleId: string, challengeId: string) => {
    // 1. Navigate immediately for instant UX
    onChallengeStart(dojo.id, moduleId, challengeId)

    // 2. Start challenge on server in background
    try {
      await startChallengeMutation.mutateAsync({
        dojoId: dojo.id,
        moduleId,
        challengeId,
        practice: false
      })
    } catch (error) {
      console.error('Failed to start challenge:', error)
    }
  }

  // Commands hook
  const commands = useCommands({
    activeChallenge,
    modules: modules.map(m => ({ ...m, challenges: m.challenges.map(c => ({ ...c, id: c.id.toString() })) })),
    activeService,
    sidebarCollapsed,
    isFullScreen,
    headerHidden: workspaceHeaderHidden,
    setActiveService,
    setSidebarCollapsed,
    setIsFullScreen: setFullScreen,
    setHeaderHidden: setWorkspaceHeaderHidden,
    onChallengeStart: handleChallengeStart,
    onChallengeClose
  })

  // Setup hotkeys
  useHotkeys({
    [hotkey.ctrlShift('p')]: () => setCommandPaletteOpen(!commandPaletteOpen),
    [hotkey.cmdShift('p')]: () => setCommandPaletteOpen(!commandPaletteOpen),
    [hotkey.ctrl('b')]: () => setSidebarCollapsed(!sidebarCollapsed),
    [hotkey.cmd('b')]: () => setSidebarCollapsed(!sidebarCollapsed),
    [hotkey.ctrl('h')]: () => setWorkspaceHeaderHidden(!workspaceHeaderHidden),
    [hotkey.cmd('h')]: () => setWorkspaceHeaderHidden(!workspaceHeaderHidden),
    ['f11']: () => setFullScreen(!isFullScreen),
    ['escape']: () => isFullScreen && setFullScreen(false),
    [hotkey.ctrl('1')]: () => workspaceData?.active && setActiveService('terminal'),
    [hotkey.ctrl('2')]: () => workspaceData?.active && setActiveService('code'),
    [hotkey.ctrl('3')]: () => workspaceData?.active && setActiveService('desktop'),
  }, [isFullScreen, workspaceData?.active])

  // Auto-expand module and use preferred service
  useEffect(() => {
    if (activeChallenge) {
      setActiveService(preferredService)
      // Don't auto-hide workspace header anymore since we want it visible by default
    }
  }, [activeChallenge.challengeId, preferredService, setActiveService])

  // Clear isStarting when workspace becomes active
  useEffect(() => {
    if (workspaceData?.active && activeChallenge?.isStarting) {
      setActiveChallenge({
        ...activeChallenge,
        isStarting: false
      })
    }
  }, [workspaceData?.active, activeChallenge?.isStarting, activeChallenge, setActiveChallenge])

  // Cached Canvas for text measurement (create once, reuse)
  const getTextMeasureCanvas = (() => {
    let canvas: HTMLCanvasElement | null = null
    let context: CanvasRenderingContext2D | null = null

    return () => {
      // Only create canvas on client side
      if (typeof document === 'undefined') {
        return null
      }

      if (!canvas || !context) {
        canvas = document.createElement('canvas')
        context = canvas.getContext('2d')
        if (context) {
          context.font = '500 14px Inter, system-ui, sans-serif'
        }
      }
      return context
    }
  })()

  // Calculate optimal sidebar width based on actual text rendering requirements
  const calculateOptimalSidebarWidth = () => {
    if (!currentModule) {
      return 25 // Default fallback
    }

    const allTexts: string[] = []

    // Add challenge titles
    if (currentModule.challenges) {
      currentModule.challenges.forEach(challenge => {
        if (challenge.name) allTexts.push(challenge.name)
      })
    }

    // Add learning material titles
    if (currentModule.resources) {
      currentModule.resources.forEach(resource => {
        if (resource.name) allTexts.push(resource.name)
      })
    }

    // Add module name and dojo name
    if (currentModule.name) allTexts.push(currentModule.name)
    if (dojo.name) allTexts.push(dojo.name)

    // If no texts found, use default
    if (allTexts.length === 0) {
      return 25
    }

    // Find the longest text
    const longestText = allTexts.reduce((a, b) => a.length > b.length ? a : b)

    // Measure actual text width using cached Canvas (optimal performance)
    const measureTextWidth = (text: string): number => {
      const context = getTextMeasureCanvas()
      if (context) {
        return Math.ceil(context.measureText(text).width) + 2 // +2px safety margin
      } else {
        // Fallback to character estimation if Canvas fails
        return text.length * 8.5 // Approximate Inter font width
      }
    }

    const textWidth = measureTextWidth(longestText)

    // Account for UI components around the text
    const padding = 48 // px-6 = 24px each side
    const margins = 24 // gaps and spacing
    const iconsBadges = 60 // info badges and icons
    const controls = 84 // header control buttons

    const totalRequiredWidth = textWidth + padding + margins + iconsBadges + controls

    // Convert to percentage of screen width (assuming 1920px base)
    const screenWidth = window?.innerWidth || 1920
    const requiredPercentage = (totalRequiredWidth / screenWidth) * 100

    // Apply limits: minimum 20%, maximum 50%
    const calculatedWidth = Math.min(Math.max(requiredPercentage, 20), 50)


    return Math.round(calculatedWidth * 10) / 10 // Round to 1 decimal
  }

  const optimalSidebarWidth = calculateOptimalSidebarWidth()


  // Full screen mode
  if (isFullScreen) {
    return (
      <FullScreenWorkspace
        activeChallenge={activeChallenge}
        activeService={activeService}
        workspaceStatus={workspaceData}
        workspaceData={workspaceData}
      />
    )
  }

  return (
    <div className="h-screen">
      <ResizablePanelGroup direction="horizontal" className="h-full">
        {/* Sidebar Panel */}
        <ResizablePanel
          defaultSize={sidebarCollapsed ? 3 : optimalSidebarWidth}
          minSize={3}
          maxSize={50}
          className={sidebarCollapsed ? "max-w-[48px]" : "min-w-[200px]"}
          onResize={(size) => {
            if (sidebarCollapsed && size > 10) {
              setSidebarCollapsed(false)
            }
          }}
        >
          <WorkspaceSidebar
            module={currentModule ? { ...currentModule, challenges: currentModule.challenges.map(c => ({ ...c, id: c.id.toString() })) } : { id: '', name: 'Module', challenges: [] }}
            dojoName={dojo.name}
            activeChallenge={activeChallenge}
            activeResource={resource?.id}
            sidebarCollapsed={sidebarCollapsed}
            isResizing={false}
            headerHidden={workspaceHeaderHidden}
            onSidebarCollapse={setSidebarCollapsed}
            onHeaderToggle={setWorkspaceHeaderHidden}
            onChallengeStart={handleChallengeStart}
            onChallengeClose={onChallengeClose}
            onResizeStart={() => {}}
            onResourceSelect={onResourceSelect}
            isPending={startChallengeMutation.isPending}
          />
        </ResizablePanel>

        <ResizableHandle
          withHandle
          onDoubleClick={() => setSidebarCollapsed(!sidebarCollapsed)}
        />

        {/* Main Workspace Panel */}
        <ResizablePanel defaultSize={sidebarCollapsed ? 97 : (100 - optimalSidebarWidth)}>
          <div className="flex flex-col h-full bg-background">
            {/* Unified animated header for both challenges and resources */}
            <AnimatedWorkspaceHeader
              activeChallenge={activeChallenge}
              dojoName={dojo.name}
              moduleName={currentModule?.name || 'Module'}
              activeService={activeService}
              workspaceActive={workspaceData?.active || false}
              activeResource={resource}
              activeResourceTab={activeResourceTab}
              onResourceTabChange={setActiveResourceTab}
              isFullScreen={isFullScreen}
              headerHidden={workspaceHeaderHidden}
              onServiceChange={setActiveService}
              onFullScreenToggle={() => setFullScreen(!isFullScreen)}
              onClose={onChallengeClose}
              onResourceClose={() => {
                if (onResourceSelect) {
                  onResourceSelect(null)
                }
              }}
            />

            <WorkspaceContent
              workspaceActive={workspaceData?.active || false}
              workspaceData={workspaceData}
              activeService={activeService}
              activeResource={resource}
              activeResourceTab={activeResourceTab}
              activeChallenge={activeChallenge}
              dojoName={dojo.name}
              moduleName={currentModule?.name || 'Module'}
              isStarting={activeChallenge?.isStarting || false}
              onResourceClose={() => {
                if (onResourceSelect) {
                  onResourceSelect(null)
                }
              }}
              onChallengeClose={onChallengeClose}
              onServiceChange={setActiveService}
              onResourceTabChange={setActiveResourceTab}
            />
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>

      {/* Command Palette */}
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        commands={commands}
      />
    </div>
  )
}