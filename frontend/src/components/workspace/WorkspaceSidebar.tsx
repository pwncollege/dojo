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
  X,
  GripVertical,
  BookOpen,
  Video,
  FileText,
  ExternalLink
} from 'lucide-react'
import { ChallengePopoverContent } from '@/components/challenge/ChallengePopover'
import { WorkspaceUnifiedItemsList } from './WorkspaceUnifiedItemsList'
import { useWorkspaceSidebar, useWorkspaceView, useWorkspaceResource, useWorkspaceStore } from '@/stores'
import { cn } from '@/lib/utils'
import type { Challenge, Resource, DojoModule } from '@/types/api'

interface WorkspaceSidebarProps {
  module: DojoModule & {
    challenges: Challenge[]
  }
  dojoName: string
  activeResource?: string // ID of active resource
  onChallengeStart: (moduleId: string, challengeId: string) => void
  onChallengeClose: () => void
  onResourceSelect?: (resourceId: string | null) => void
  isPending?: boolean
}

export function WorkspaceSidebar({
  module,
  dojoName,
  activeResource,
  onChallengeStart,
  onChallengeClose,
  onResourceSelect,
  isPending = false
}: WorkspaceSidebarProps) {
  // Use workspace store directly instead of props drilling
  const { sidebarCollapsed, setSidebarCollapsed } = useWorkspaceSidebar()
  const { setActiveResource } = useWorkspaceResource()
  const activeChallenge = useWorkspaceStore(state => state.activeChallenge)
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

{(() => {
                      // Count materials from unified_items or fallback to resources
                      const materialsCount = module.unified_items
                        ? module.unified_items.filter(item =>
                            item.item_type === 'resource' &&
                            item.type !== 'header' &&
                            (item.type === 'lecture' || item.type === 'markdown')
                          ).length
                        : (module.resources?.filter(r => r.type === 'lecture' || r.type === 'markdown').length || 0)

                      return materialsCount > 0 ? (
                        <>
                          <div className="w-px h-4 bg-muted-foreground/20" />
                          <div className="flex items-center gap-1 px-1.5 py-0.5">
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <BookOpen className="h-3 w-3 text-muted-foreground" />
                              </TooltipTrigger>
                              <TooltipContent>
                                <p>{materialsCount} Materials</p>
                              </TooltipContent>
                            </Tooltip>
                            <span className="text-xs font-medium text-muted-foreground">{materialsCount}</span>
                          </div>
                        </>
                      ) : null
                    })()}
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {/* Action buttons - grouped separately from info */}
          <div className={`flex items-center ${sidebarCollapsed ? 'flex-col gap-1 py-[4px] h-[41px]' : 'gap-0.5'} flex-shrink-0`}>
            {!sidebarCollapsed && (
              <div className="flex items-center gap-0.5 p-0.5 bg-muted/20 rounded-md">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
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
                      className="h-7 w-7 p-0 hover:bg-primary/10 hover:text-primary"
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Minimize workspace</p>
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
                    onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
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

      {/* Content List with Unified Items */}
      {!sidebarCollapsed ? (
        <ScrollArea className="flex-1 h-full">
          <div className="p-3">
            <WorkspaceUnifiedItemsList
              unifiedItems={module.unified_items}
              resources={module.resources}
              challenges={module.challenges}
              moduleId={module.id}
              activeResource={activeResource}
              onChallengeStart={onChallengeStart}
              onResourceSelect={onResourceSelect}
              isPending={isPending}
            />
          </div>
        </ScrollArea>
      ) : (
        /* Collapsed Sidebar - Show sections with icons */
        <ScrollArea className="flex-1">
          <div className="flex flex-col items-center py-4 gap-1">
            {(() => {
              // Use the same section logic as WorkspaceUnifiedItemsList
              const finalUnifiedItems = module.unified_items || []

              if (finalUnifiedItems.length === 0) return null

              let currentSection = ''
              const sections: Array<{ header: string; items: any[] }> = []
              let currentItems: any[] = []

              // Group items by sections based on headers
              finalUnifiedItems.forEach((item) => {
                if (item.item_type === 'resource' && item.type === 'header') {
                  // Start a new section
                  if (currentItems.length > 0) {
                    sections.push({ header: currentSection, items: currentItems })
                  }
                  currentSection = item.content || item.name || 'Untitled Section'
                  currentItems = []
                } else {
                  currentItems.push(item)
                }
              })

              // Add the final section
              if (currentItems.length > 0) {
                sections.push({ header: currentSection, items: currentItems })
              }

              // If no headers were found, group by type
              if (sections.length === 0) {
                const resourceItems = finalUnifiedItems.filter(item =>
                  item.item_type === 'resource' && item.type !== 'header'
                )
                const challengeItems = finalUnifiedItems.filter(item =>
                  item.item_type === 'challenge'
                )

                if (resourceItems.length > 0) {
                  sections.push({ header: 'Learning Materials', items: resourceItems })
                }
                if (challengeItems.length > 0) {
                  sections.push({ header: 'Challenges', items: challengeItems })
                }
              }

              return sections.map((section, sectionIndex) => (
                <div key={`section-${sectionIndex}`} className="flex flex-col items-center gap-1">
                  {/* Section items */}
                  {section.items.map((item, index) => {
                    if (item.item_type === 'resource' && item.type !== 'header' && item.expandable !== false) {
                      const isActiveResource = activeResource === item.id
                      const hasVideo = item.type === 'lecture' && item.video

                      return (
                        <div
                          key={`${item.id}-${index}`}
                          className={cn(
                            "w-8 h-8 rounded-md flex items-center justify-center transition-all cursor-pointer",
                            isActiveResource
                              ? "bg-primary text-primary-foreground shadow-sm"
                              : "hover:bg-muted/70"
                          )}
                          onClick={() => {
                            setActiveResource(item.id)
                            if (onResourceSelect) {
                              onResourceSelect(item.id)
                            }
                          }}
                          title={item.name}
                        >
                          {item.type === 'lecture' ? (
                            <Video className="h-4 w-4" />
                          ) : (
                            <FileText className="h-4 w-4" />
                          )}
                        </div>
                      )
                    } else if (item.item_type === 'challenge') {
                      // Find challenge index for numbering
                      const challengeIndex = module.challenges.findIndex(c => c.id === item.id)
                      const challengeNumber = challengeIndex + 1
                      const isActive = activeChallenge?.challengeId === item.id
                      const challenge = module.challenges.find(c => c.id === item.id)

                      return (
                        <Popover key={`${item.id}-${index}`}>
                          <PopoverTrigger asChild>
                            <div
                              className={cn(
                                "w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium transition-all cursor-pointer",
                                isActive
                                  ? "bg-primary text-primary-foreground shadow-sm"
                                  : "hover:bg-muted/70"
                              )}
                              title={`${challengeNumber}. ${item.name}`}
                            >
                              {challenge?.solved ? (
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
                              onStartChallenge={() => onChallengeStart(module.id, item.id)}
                              isPending={isPending}
                            />
                          </PopoverContent>
                        </Popover>
                      )
                    }

                    return null
                  })}

                  {/* Section separator */}
                  {sectionIndex < sections.length - 1 && (
                    <div className="w-6 h-px bg-border/50 my-2" />
                  )}
                </div>
              ))
            })()}
          </div>
        </ScrollArea>
      )}
    </div>
  )
}
