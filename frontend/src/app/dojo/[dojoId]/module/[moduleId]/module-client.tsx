'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { Badge } from '@/components/ui/badge'
import { Markdown } from '@/components/ui/markdown'
import { UnifiedItemsList } from '@/components/module/UnifiedItemsList'
import { useDojoStore, useHeaderState, useAuthStore } from '@/stores'
import { ArrowLeft } from 'lucide-react'
import { motion } from 'framer-motion'

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

interface Module {
  id: string
  name: string
  description?: string
  unified_items?: Array<{
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
  }>
  resources?: Resource[]
  challenges: Challenge[]
}

interface DojoDetail {
  id: string
  name: string
  description?: string
  official: boolean
  award?: {
    belt?: string
    emoji?: string
  }
  modules: Module[]
}

interface ModulePageClientProps {
  dojo: DojoDetail
  module: Module
  dojoId: string
  moduleId: string
}

export function ModulePageClient({ dojo, module, dojoId, moduleId }: ModulePageClientProps) {
  const { isHeaderHidden } = useHeaderState()
  const [headerOffset, setHeaderOffset] = useState(16)
  const [lastScrollY, setLastScrollY] = useState(0)

  // Direct state access to avoid selector issues
  const solvesMap = useDojoStore(state => state.solves)
  const isAuthenticated = useAuthStore(state => state.isAuthenticated)


  useEffect(() => {
    // Only fetch solves if user is authenticated
    if (isAuthenticated) {
      useDojoStore.getState().fetchSolves(dojoId)
    }
  }, [dojoId, isAuthenticated])

  // Track header position and calculate dynamic offset
  useEffect(() => {
    const handleScroll = () => {
      const currentScrollY = window.scrollY

      if (isHeaderHidden) {
        setHeaderOffset(0)
        setLastScrollY(currentScrollY)
        return
      }

      if (currentScrollY > lastScrollY && currentScrollY > 100) {
        setHeaderOffset(0)
      } else if (currentScrollY < lastScrollY) {
        setHeaderOffset(16)
      }

      setLastScrollY(currentScrollY)
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [lastScrollY, isHeaderHidden])

  // Get solves from store
  const solves = solvesMap[`${dojoId}-all`] || []

  // Get solved challenge IDs for this module
  const solvedChallengeIds = new Set(
    solves
      ?.filter(solve => solve.module_id === moduleId)
      .map(solve => solve.challenge_id) || []
  )

  const completedChallenges = module.challenges.filter(
    challenge => solvedChallengeIds.has(challenge.id)
  ).length

  return (
    <motion.div
      className="min-h-screen bg-background text-foreground p-6"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] }}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="mb-8">
          <Link
            href={`/dojo/${dojoId}`}
            className="inline-flex items-center text-muted-foreground hover:text-foreground mb-4"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to {dojoId}
          </Link>

          <div className="mb-6">
            <h1 className="text-4xl font-bold mb-2">{module.name}</h1>

            <div className="flex items-center gap-4">
              <Badge variant="outline">{dojoId}</Badge>
              <span className="text-sm text-muted-foreground">
                {completedChallenges}/{module.challenges.length} challenges completed
              </span>
            </div>
          </div>
        </div>

        <div className="space-y-8">
          {module.description && (
            <Markdown>{module.description}</Markdown>
          )}

          <UnifiedItemsList
            unifiedItems={module.unified_items}
            resources={module.resources}
            challenges={module.challenges}
            dojoId={dojoId}
            moduleId={moduleId}
            dojoName={dojo.name}
            moduleName={module.name}
            solvedChallengeIds={solvedChallengeIds}
            headerOffset={headerOffset}
          />
        </div>
      </div>
    </motion.div>
  )
}