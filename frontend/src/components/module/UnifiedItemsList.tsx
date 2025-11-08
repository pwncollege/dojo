'use client'

import { useState } from 'react'
import { ResourceItem } from './ResourceItem'
import { ChallengeItem } from './ChallengeItem'
import { useWorkspaceStore } from '@/stores'

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

interface UnifiedItemsListProps {
  unifiedItems?: APIUnifiedItem[]
  resources?: Resource[]
  challenges: Challenge[]
  dojoId: string
  moduleId: string
  dojoName: string
  moduleName: string
  solvedChallengeIds: Set<string>
  headerOffset: number
}

export function UnifiedItemsList({
  unifiedItems: apiUnifiedItems,
  resources,
  challenges,
  dojoId,
  moduleId,
  dojoName,
  moduleName,
  solvedChallengeIds,
  headerOffset
}: UnifiedItemsListProps) {
  const [openItem, setOpenItem] = useState<string | null>(null)
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

  return (
    <div className="space-y-4">
      {finalUnifiedItems.map((item, index) => {
        const itemKey = `item-${index}`
        const isOpen = openItem === itemKey

        if (item.item_type === 'resource') {
          // Check if previous item was a header
          const prevItem = index > 0 ? finalUnifiedItems[index - 1] : null
          const isAfterHeader = prevItem?.item_type === 'resource' && prevItem?.type === 'header'

          return (
            <ResourceItem
              key={`${item.id}-${index}`}
              resource={item}
              dojoId={dojoId}
              moduleId={moduleId}
              isOpen={isOpen}
              onToggle={() => setOpenItem(isOpen ? null : itemKey)}
              isAfterHeader={isAfterHeader}
            />
          )
        } else if (item.item_type === 'challenge') {
          const isSolved = solvedChallengeIds.has(item.id)
          const isInProgress = activeChallenge &&
            activeChallenge.dojoId === dojoId &&
            activeChallenge.moduleId === moduleId &&
            activeChallenge.challengeId === item.id
          const challengeIndex = item.challenge_index ?? challenges.findIndex(c => c.id === item.id)

          return (
            <ChallengeItem
              key={`${item.id}-${index}`}
              challenge={item}
              dojoId={dojoId}
              moduleId={moduleId}
              dojoName={dojoName}
              moduleName={moduleName}
              challengeIndex={challengeIndex}
              isSolved={isSolved}
              isInProgress={isInProgress}
              isOpen={isOpen}
              onToggle={() => setOpenItem(isOpen ? null : itemKey)}
              headerOffset={headerOffset}
            />
          )
        }

        return null
      })}
    </div>
  )
}