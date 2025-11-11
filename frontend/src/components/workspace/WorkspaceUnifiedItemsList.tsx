'use client'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import {
  CheckCircle,
  Circle,
  Play,
  Info,
  BookOpen,
  Video,
  FileText,
} from 'lucide-react'
import { ChallengePopoverContent } from '@/components/challenge/ChallengePopover'
import { useWorkspaceResource, useWorkspaceStore } from '@/stores'
import { cn } from '@/lib/utils'

interface Resource {
  id: string
  name: string
  type: 'markdown' | 'lecture' | 'header'
  content?: string
  video?: string
  playlist?: string
  slides?: string
  expandable?: boolean
  resource_index?: number
}

interface Challenge {
  id: string
  name: string
  required: boolean
  description?: string
  challenge_index?: number
  unified_index?: number
  solved?: boolean
}

type UnifiedItem = (Resource & { item_type: 'resource' }) | (Challenge & { item_type: 'challenge' })

interface APIUnifiedItem {
  item_type: 'resource' | 'challenge'
  id: string
  name?: string
  type?: 'markdown' | 'lecture' | 'header'
  content?: string
  video?: string
  playlist?: string
  slides?: string
  expandable?: boolean
  description?: string
  required?: boolean
}

interface WorkspaceUnifiedItemsListProps {
  unifiedItems?: APIUnifiedItem[]
  resources?: Resource[]
  challenges: Challenge[]
  moduleId: string
  activeResource?: string
  onChallengeStart: (moduleId: string, challengeId: string) => void
  onResourceSelect?: (resourceId: string | null) => void
  isPending?: boolean
}

export function WorkspaceUnifiedItemsList({
  unifiedItems: apiUnifiedItems,
  resources,
  challenges,
  moduleId,
  activeResource,
  onChallengeStart,
  onResourceSelect,
  isPending = false
}: WorkspaceUnifiedItemsListProps) {
  const { setActiveResource } = useWorkspaceResource()
  const activeChallenge = useWorkspaceStore(state => state.activeChallenge)

  // Use unified_items from API if available, otherwise construct from resources/challenges
  let finalUnifiedItems: (APIUnifiedItem | UnifiedItem)[] = []

  if (apiUnifiedItems && apiUnifiedItems.length > 0) {
    // Use the unified items from the API
    finalUnifiedItems = apiUnifiedItems
  } else {
    // Fallback: construct unified_items exactly like the backend
    const items: Array<[number, UnifiedItem]> = []

    // Add resources with their resource_index
    if (resources) {
      resources.forEach((resource) => {
        items.push([resource.resource_index ?? 0, { ...resource, item_type: 'resource' as const }])
      })
    }

    // Add challenges with their unified_index or challenge_index + 1000
    challenges.forEach((challenge) => {
      const index = challenge.unified_index !== undefined ?
        challenge.unified_index :
        1000 + (challenge.challenge_index ?? 0)
      items.push([index, { ...challenge, item_type: 'challenge' as const }])
    })

    // Sort by index and extract items
    items.sort((a, b) => a[0] - b[0])
    finalUnifiedItems = items.map(([_, item]) => item)
  }

  if (finalUnifiedItems.length === 0) {
    return null
  }

  let currentSection = ''
  const sections: Array<{ header: string; items: (APIUnifiedItem | UnifiedItem)[] }> = []
  let currentItems: (APIUnifiedItem | UnifiedItem)[] = []

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
      item.item_type === 'resource' && item.type !== 'header' && item.expandable !== false
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

  return (
    <div className="space-y-4">
      {sections.map((section, sectionIndex) => (
        <div key={`section-${sectionIndex}`}>
          {section.header && (
            <div className="px-2 pb-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider flex items-center gap-2">
                {section.items.some(item => item.item_type === 'resource') ? (
                  <>
                    <BookOpen className="h-3 w-3 text-primary" />
                    <span className="text-primary">{section.header}</span>
                  </>
                ) : (
                  <>
                    <Circle className="h-3 w-3 text-primary" />
                    <span className="text-primary">{section.header}</span>
                  </>
                )}
              </h3>
            </div>
          )}

          <div className="space-y-1">
            {section.items.map((item, index) => {
              if (item.item_type === 'resource' && item.type !== 'header' && item.expandable !== false) {
                const isActiveResource = activeResource === item.id
                const hasVideo = item.type === 'lecture' && item.video
                const hasSlides = item.type === 'lecture' && item.slides

                return (
                  <div
                    key={`${item.id}-${index}`}
                    className={cn(
                      "group flex items-center justify-between gap-2 p-2.5 rounded-md text-sm transition-all cursor-pointer",
                      isActiveResource
                        ? "bg-primary/10 text-sm border-primary"
                        : "hover:bg-muted/70"
                    )}
                    onClick={() => {
                      // In workspace sidebar, always select the resource (don't allow deselection)
                      setActiveResource(item.id)
                      if (onResourceSelect) {
                        onResourceSelect(item.id)
                      }
                    }}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      {item.type === 'lecture' ? (
                        <Video className={cn("h-4 w-4 flex-shrink-0", isActiveResource ? "text-primary" : "text-muted-foreground")} />
                      ) : (
                        <FileText className={cn("h-4 w-4 flex-shrink-0", isActiveResource ? "text-primary" : "text-muted-foreground")} />
                      )}
                      <span className="truncate font-medium">{item.name}</span>
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
              } else if (item.item_type === 'challenge') {
                const isActive = activeChallenge?.challengeId === item.id

                return (
                  <div
                    key={`${item.id}-${index}`}
                    className={cn(
                      "group flex items-center justify-between gap-2 p-2.5 rounded-md text-sm transition-all",
                      isActive
                        ? "bg-primary/10 text-sm border-primary"
                        : "hover:bg-muted/70 cursor-pointer"
                    )}
                    onClick={() => !isActive && onChallengeStart(moduleId, item.id)}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      {(item as Challenge).solved ? (
                        <CheckCircle className="h-4 w-4 flex-shrink-0 text-primary" />
                      ) : (
                        <Circle className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
                      )}
                      <span className="truncate font-medium">{item.name}</span>
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
                            challenge={item as Challenge}
                            isActive={isActive}
                            onStartChallenge={() => onChallengeStart(moduleId, item.id)}
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
                            onChallengeStart(moduleId, item.id)
                          }}
                          disabled={isPending}
                        >
                          <Play className="h-3 w-3" />
                        </Button>
                      )}
                    </div>
                  </div>
                )
              }

              return null
            })}
          </div>

          {/* Add separator between sections */}
          {sectionIndex < sections.length - 1 && (
            <div className="border-t border-border/50 my-2" />
          )}
        </div>
      ))}
    </div>
  )
}