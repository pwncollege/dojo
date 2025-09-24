import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Badge } from '@/components/ui/badge'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  CheckCircle,
  Circle,
  Play,
  Info,
  PanelLeftClose,
  PanelLeftOpen,
  Eye,
  EyeOff,
  X,
  GripVertical,
  BookOpen,
  Video,
  FileText,
  ExternalLink
} from 'lucide-react'
import { ChallengePopoverContent } from '@/components/challenge/ChallengePopover'
import { cn } from '@/lib/utils'

interface Challenge {
  id: string
  name: string
  solved?: boolean
  required?: boolean
  description?: string
}

interface Resource {
  id: string
  name: string
  type: 'markdown' | 'lecture' | 'header'
  content?: string
  video?: string
  playlist?: string
  slides?: string
  expandable?: boolean
}

interface Module {
  id: string
  name: string
  challenges: Challenge[]
  resources?: Resource[]
}

interface WorkspaceSidebarProps {
  module: Module
  dojoName: string
  activeChallenge: {
    challengeId: string
  }
  activeResource?: string // ID of active resource
  sidebarCollapsed: boolean
  sidebarWidth: number
  isResizing: boolean
  headerHidden: boolean
  onSidebarCollapse: (collapsed: boolean) => void
  onHeaderToggle: (hidden: boolean) => void
  onChallengeStart: (moduleId: string, challengeId: string) => void
  onChallengeClose: () => void
  onResizeStart: (e: React.MouseEvent) => void
  onResourceSelect?: (resourceId: string | null) => void
  isPending?: boolean
}

export function WorkspaceSidebar({
  module,
  dojoName,
  activeChallenge,
  activeResource,
  sidebarCollapsed,
  sidebarWidth,
  isResizing,
  headerHidden,
  onSidebarCollapse,
  onHeaderToggle,
  onChallengeStart,
  onChallengeClose,
  onResizeStart,
  onResourceSelect,
  isPending = false
}: WorkspaceSidebarProps) {
  return (
    <div
      className="bg-background flex flex-col h-full w-full"
    >

      {/* Header */}
      <div className="border-b px-6 py-3 animate-in fade-in slide-in-from-top-2 duration-300 delay-100">
        <div className={`flex items-center ${sidebarCollapsed ? 'justify-center' : 'justify-between'}`}>
          {!sidebarCollapsed ? (
            <div className="flex items-start justify-between w-full gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <h1 className="text-lg font-semibold leading-tight truncate">{module.name}</h1>
                    <p className="text-xs text-muted-foreground truncate mt-0.5">{dojoName}</p>
                  </div>

                  {/* Info panel - grouped info badges */}
                  <div className="flex items-center gap-1 p-0.5 bg-muted/20 rounded-md flex-shrink-0">
                    <div className="flex items-center gap-1 px-1.5 py-0.5">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Circle className="h-3 w-3 text-muted-foreground" />
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>{module.challenges.length} Challenges</p>
                        </TooltipContent>
                      </Tooltip>
                      <span className="text-xs font-medium text-muted-foreground">{module.challenges.length}</span>
                    </div>

                    {module.resources && module.resources.filter(r => r.type === 'lecture' || r.type === 'markdown').length > 0 && (
                      <>
                        <div className="w-px h-4 bg-muted-foreground/20" />
                        <div className="flex items-center gap-1 px-1.5 py-0.5">
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <BookOpen className="h-3 w-3 text-muted-foreground" />
                            </TooltipTrigger>
                            <TooltipContent>
                              <p>{module.resources.filter(r => r.type === 'lecture' || r.type === 'markdown').length} Materials</p>
                            </TooltipContent>
                          </Tooltip>
                          <span className="text-xs font-medium text-muted-foreground">{module.resources.filter(r => r.type === 'lecture' || r.type === 'markdown').length}</span>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {/* Action buttons - grouped separately from info */}
          <div className={`flex items-center ${sidebarCollapsed ? 'flex-col gap-1' : 'gap-0.5'} flex-shrink-0`}>
            {!sidebarCollapsed && (
              <div className="flex items-center gap-0.5 p-0.5 bg-muted/20 rounded-md">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onHeaderToggle(!headerHidden)}
                      className="h-7 w-7 p-0 hover:bg-primary/10 hover:text-primary"
                    >
                      {headerHidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>{headerHidden ? "Show header (Ctrl+H)" : "Hide header (Ctrl+H)"}</p>
                  </TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onSidebarCollapse(!sidebarCollapsed)}
                      className="h-7 w-7 p-0 hover:bg-primary/10 hover:text-primary"
                    >
                      <PanelLeftClose className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Collapse sidebar (Ctrl+B)</p>
                  </TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={onChallengeClose}
                      className="h-7 w-7 p-0 hover:bg-destructive/10 hover:text-destructive"
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Close workspace</p>
                  </TooltipContent>
                </Tooltip>
              </div>
            )}

            {sidebarCollapsed && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onSidebarCollapse(!sidebarCollapsed)}
                    className="h-8 w-8 p-0 hover:bg-primary/10 hover:text-primary"
                  >
                    <PanelLeftOpen className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p>Expand sidebar (Ctrl+B)</p>
                </TooltipContent>
              </Tooltip>
            )}
          </div>
        </div>
      </div>

      {/* Content List with Resources and Challenges */}
      {!sidebarCollapsed ? (
        <ScrollArea className="flex-1 h-full">
          <div className="p-3 space-y-4">
            {/* Learning Resources Section */}
            {module.resources && module.resources.filter(r => r.type === 'lecture' || r.type === 'markdown').length > 0 && (
              <div>
                <div className="px-2 pb-2">
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                    <BookOpen className="h-3 w-3" />
                    Learning Materials
                  </h3>
                </div>
                <div className="space-y-1">
                  {module.resources
                    .filter(resource => resource.type === 'lecture' || resource.type === 'markdown')
                    .map((resource, index) => {

                    const isActiveResource = activeResource === resource.id
                    const hasVideo = resource.type === 'lecture' && resource.video
                    const hasSlides = resource.type === 'lecture' && resource.slides

                    return (
                      <div
                        key={resource.id}
                        className={cn(
                          "group flex items-center justify-between gap-2 p-2.5 rounded-md text-sm transition-all cursor-pointer",
                          isActiveResource
                            ? "bg-primary/10 text-sm border-primary"
                            : "hover:bg-muted/70"
                        )}
                        onClick={() => {
                          if (onResourceSelect) {
                            onResourceSelect(isActiveResource ? null : resource.id)
                          }
                        }}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          {resource.type === 'lecture' ? (
                            <Video className={cn("h-4 w-4 flex-shrink-0", isActiveResource ? "text-primary" : "text-muted-foreground")} />
                          ) : (
                            <FileText className={cn("h-4 w-4 flex-shrink-0", isActiveResource ? "text-primary" : "text-muted-foreground")} />
                          )}
                          <span className="truncate font-medium">{resource.name}</span>
                        </div>
                        <div className="flex items-center gap-1">
                          {(hasVideo || hasSlides) && (
                            <div className="flex items-center gap-1 mr-1">
                              {hasVideo && (
                                <Badge variant="outline" className="text-[9px] h-4 px-1">
                                  Video
                                </Badge>
                              )}
                              {hasSlides && (
                                <Badge variant="outline" className="text-[9px] h-4 px-1">
                                  Slides
                                </Badge>
                              )}
                            </div>
                          )}
                          {isActiveResource && (
                            <Play className="h-3 w-3 text-primary" />
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Separator */}
            {module.resources && module.resources.filter(r => r.type === 'lecture' || r.type === 'markdown').length > 0 && module.challenges.length > 0 && (
              <div className="border-t border-border/50 my-2" />
            )}

            {/* Challenges Section */}
            {module.challenges.length > 0 && (
              <div>
                <div className="px-2 pb-2">
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                    <Circle className="h-3 w-3" />
                    Challenges
                  </h3>
                </div>
                <div className="space-y-1">
                  {module.challenges.map((challenge) => {
                    const isActive = activeChallenge.challengeId === challenge.id

                    return (
                      <div
                        key={challenge.id}
                        className={cn(
                          "group flex items-center justify-between gap-2 p-2.5 rounded-md text-sm transition-all",
                          isActive
                            ? "bg-primary/10 text-sm border-primary"
                            : "hover:bg-muted/70 cursor-pointer"
                        )}
                        onClick={() => !isActive && onChallengeStart(module.id, challenge.id)}
                      >
                        <div className="flex items-center gap-2.5 min-w-0 flex-1">
                          {challenge.solved ? (
                            <CheckCircle className="h-4 w-4 flex-shrink-0 text-primary" />
                          ) : (
                            <Circle className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
                          )}
                          <span className="truncate font-medium">{challenge.name}</span>
                        </div>
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                          <Popover>
                            <PopoverTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 w-6 p-0 hover:bg-primary/10 hover:text-primary"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <Info className="h-3 w-3" />
                              </Button>
                            </PopoverTrigger>
                            <PopoverContent side="right" className="w-80 sm:w-96 lg:w-[28rem] p-0" align="center">
                              <ChallengePopoverContent
                                challenge={challenge}
                                isActive={isActive}
                                onStartChallenge={() => onChallengeStart(module.id, challenge.id)}
                                isPending={isPending}
                              />
                            </PopoverContent>
                          </Popover>

                          {!isActive && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 w-6 p-0 hover:bg-primary/10 hover:text-primary"
                              onClick={(e) => {
                                e.stopPropagation()
                                onChallengeStart(module.id, challenge.id)
                              }}
                              disabled={isPending}
                            >
                              <Play className="h-3 w-3" />
                            </Button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </ScrollArea>
      ) : (
        /* Collapsed Sidebar - Show challenge numbers */
        <ScrollArea className="flex-1">
          <div className="flex flex-col items-center py-4 gap-2">
            {module.challenges.map((challenge, index) => {
              const challengeNumber = index + 1
              const isActive = activeChallenge.challengeId === challenge.id

              return (
                <Popover key={challenge.id}>
                  <PopoverTrigger asChild>
                    <div
                      className={cn(
                        "w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium transition-all cursor-pointer",
                        isActive
                          ? "bg-primary text-primary-foreground shadow-sm"
                          : "hover:bg-muted/70"
                      )}
                      title={`${challengeNumber}. ${challenge.name}`}
                    >
                      {challenge.solved ? (
                        <CheckCircle className="h-4 w-4 text-primary" />
                      ) : (
                        challengeNumber
                      )}
                    </div>
                  </PopoverTrigger>
                  <PopoverContent
                    side="right"
                    className="w-80 sm:w-96 lg:w-[28rem] p-0"
                    align="center"
                  >
                    <ChallengePopoverContent
                      challenge={challenge}
                      isActive={isActive}
                      onStartChallenge={() => onChallengeStart(module.id, challenge.id)}
                      isPending={isPending}
                    />
                  </PopoverContent>
                </Popover>
              )
            })}
          </div>
        </ScrollArea>
      )}
    </div>
  )
}
