import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { SmartFlagInput } from '@/components/challenge/SmartFlagInput'
import {
  Terminal,
  Code,
  Monitor,
  Maximize2,
  Minimize2,
  ChevronLeft
} from 'lucide-react'

interface WorkspaceHeaderProps {
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
  isFullScreen: boolean
  headerHidden: boolean
  onServiceChange: (service: string) => void
  onFullScreenToggle: () => void
  onClose?: () => void
}

export function WorkspaceHeader({
  activeChallenge,
  dojoName,
  moduleName,
  activeService,
  workspaceActive,
  isFullScreen,
  headerHidden,
  onServiceChange,
  onFullScreenToggle,
  onClose
}: WorkspaceHeaderProps) {
  if (headerHidden) {
    return null
  }

  return (
    <div className="border-b bg-background backdrop-blur-md shadow-sm">
      <div className="px-6 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            {/* Back button */}
            {onClose && (
              <Button
                variant="ghost"
                size="icon"
                onClick={onClose}
                className="hover:bg-primary/10 hover:text-primary h-8 w-8 transition-colors"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
            )}

            <div className="flex items-center gap-3">
              <div className="p-1.5 rounded-lg bg-primary/10">
                <Terminal className="h-4 w-4 text-primary" />
              </div>
              <div>
                <h1 className="text-lg font-semibold leading-tight">{activeChallenge.name}</h1>
                <div className="flex items-center gap-3 mt-0.5">
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span>{dojoName} → {moduleName}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right side: Smart Flag Input, Service Tabs and Controls */}
          <div className="flex items-center gap-3">
            {/* Smart Flag Input */}
            <SmartFlagInput
              dojoId={activeChallenge.dojoId}
              moduleId={activeChallenge.moduleId}
              challengeId={activeChallenge.challengeId}
            />

            {/* Service Tabs */}
            {workspaceActive && (
              <Tabs value={activeService} onValueChange={onServiceChange}>
                <TabsList className="bg-muted/50 h-8">
                  <TabsTrigger value="terminal" className="gap-1.5 h-7 px-3 text-xs">
                    <Terminal className="h-3 w-3" />
                    Terminal
                  </TabsTrigger>
                  <TabsTrigger value="code" className="gap-1.5 h-7 px-3 text-xs">
                    <Code className="h-3 w-3" />
                    Editor
                  </TabsTrigger>
                  <TabsTrigger value="desktop" className="gap-1.5 h-7 px-3 text-xs">
                    <Monitor className="h-3 w-3" />
                    Desktop
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            )}

            {/* Full Screen Controls */}
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                onClick={onFullScreenToggle}
                className="hover:bg-primary/10 hover:text-primary h-8 w-8 transition-colors"
                title={isFullScreen ? "Exit fullscreen" : "Enter fullscreen"}
              >
                {isFullScreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}