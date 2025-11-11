'use client'

import { useEffect, useMemo, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useWorkspaceStore, useDojoStore } from '@/stores'
import { DojoWorkspaceLayout } from '@/components/layout/DojoWorkspaceLayout'
import { motion } from 'framer-motion'
import { dojoService } from '@/services/dojo'

export function WorkspaceOverlayProvider() {
  const pathname = usePathname()
  const router = useRouter()
  const activeChallenge = useWorkspaceStore(state => state.activeChallenge)
  const setActiveChallenge = useWorkspaceStore(state => state.setActiveChallenge)
  const isMinimized = useWorkspaceStore(state => state.isMinimized)
  const setMinimized = useWorkspaceStore(state => state.setMinimized)
  const solvesMap = useDojoStore(state => state.solves)

  const [dojoData, setDojoData] = useState<any>(null)
  const [moduleData, setModuleData] = useState<any>(null)

  // Parse URL to determine if we're on workspace page
  const urlParts = pathname.split('/')
  const workspaceIndex = urlParts.indexOf('workspace')
  const isOnWorkspacePage = workspaceIndex !== -1
  const urlDojoId = isOnWorkspacePage ? urlParts[urlParts.indexOf('dojo') + 1] : null
  const urlModuleId = isOnWorkspacePage ? urlParts[urlParts.indexOf('module') + 1] : null
  const urlChallengeId = isOnWorkspacePage ? urlParts[workspaceIndex + 2] : null

  // Sync URL with state: If URL has workspace but state doesn't, update state
  useEffect(() => {
    if (isOnWorkspacePage && urlDojoId && urlModuleId && urlChallengeId) {
      // URL indicates workspace should be open
      if (!activeChallenge || activeChallenge.challengeId !== urlChallengeId) {
        setActiveChallenge({
          dojoId: urlDojoId,
          moduleId: urlModuleId,
          challengeId: urlChallengeId,
          challengeName: urlChallengeId, // Will be updated when data loads
          dojoName: urlDojoId,
          moduleName: urlModuleId,
          isStarting: false
        })
      }
      // Always ensure workspace is not minimized when on workspace URL
      setMinimized(false)
    }
  }, [pathname, isOnWorkspacePage, urlDojoId, urlModuleId, urlChallengeId])

  // Fetch dojo and module data when activeChallenge changes
  useEffect(() => {
    if (!activeChallenge) {
      setDojoData(null)
      setModuleData(null)
      return
    }

    const { dojoId, moduleId } = activeChallenge

    // Fetch dojo details
    dojoService.getDojoDetail(dojoId).then(response => {
      setDojoData(response.dojo)
      const module = response.dojo.modules.find((m: any) => m.id === moduleId)
      setModuleData(module)

      // Update activeChallenge with proper names
      const challenge = module?.challenges?.find((c: any) => c.id === activeChallenge.challengeId)
      if (challenge) {
        setActiveChallenge({
          ...activeChallenge,
          challengeName: challenge.name,
          dojoName: response.dojo.name,
          moduleName: module.name
        })
      }
    }).catch(error => {
      console.error('Failed to fetch dojo data for workspace:', error)
    })
  }, [activeChallenge?.dojoId, activeChallenge?.moduleId])

  // Don't render if no active challenge
  if (!activeChallenge) {
    return null
  }

  // Show loading state while fetching data
  if (!dojoData || !moduleData) {
    const shouldShow = isOnWorkspacePage && !isMinimized
    return (
      <motion.div
        initial={false}
        animate={shouldShow ? 'open' : 'closed'}
        variants={{
          open: {
            opacity: 1,
            scale: 1,
          },
          closed: {
            opacity: 0,
            scale: 0.95,
          }
        }}
        transition={{
          type: 'spring',
          stiffness: 400,
          damping: 25
        }}
        className="fixed inset-0 bg-background flex items-center justify-center"
        style={{
          zIndex: shouldShow ? 50 : -1,
          pointerEvents: shouldShow ? 'auto' : 'none',
        }}
      >
        <div className="text-muted-foreground">Loading workspace...</div>
      </motion.div>
    )
  }

  const { dojoId, moduleId } = activeChallenge

  // Get solved challenge IDs
  const solves = solvesMap[`${dojoId}-all`] || []
  const solvedChallengeIds = new Set(
    solves
      ?.filter(solve => solve.module_id === moduleId)
      .map(solve => solve.challenge_id) || []
  )

  // Enrich module with solved status
  const enrichedModule = {
    ...moduleData,
    challenges: moduleData.challenges.map((challenge: any) => ({
      ...challenge,
      solved: solvedChallengeIds.has(challenge.id)
    }))
  }

  // Workspace handlers
  const handleChallengeStart = (_dojoId: string, _moduleId: string, _challengeId: string) => {
    // Just update workspace state, no navigation
  }

  const handleResourceSelect = (_resourceId: string | null) => {
    // Just update workspace state, no navigation
  }

  const handleWorkspaceClose = () => {
    console.log('Minimizing workspace...')
    // Always minimize to module page
    if (activeChallenge) {
      router.push(`/dojo/${activeChallenge.dojoId}/module/${activeChallenge.moduleId}`, { scroll: false })
    }
  }

  // Show workspace only when on workspace URL
  const shouldShowWorkspace = isOnWorkspacePage && !isMinimized

  return (
    <motion.div
      initial={false}
      animate={shouldShowWorkspace ? 'open' : 'closed'}
      variants={{
        open: {
          opacity: 1,
          scale: 1,
        },
        closed: {
          opacity: 0,
          scale: 0.95,
        }
      }}
      transition={{
        type: 'spring',
        stiffness: 400,
        damping: 25
      }}
      className="fixed inset-0 bg-background"
      style={{
        zIndex: shouldShowWorkspace ? 50 : -1,
        pointerEvents: shouldShowWorkspace ? 'auto' : 'none',
      }}
    >
      <motion.div
        className="h-full w-full"
        animate={shouldShowWorkspace ? { opacity: 1 } : { opacity: 0 }}
        transition={{ duration: 0.2, delay: shouldShowWorkspace ? 0.1 : 0 }}
      >
        <DojoWorkspaceLayout
          dojo={dojoData}
          modules={[enrichedModule]}
          onChallengeStart={handleChallengeStart}
          onChallengeClose={handleWorkspaceClose}
          onResourceSelect={handleResourceSelect}
        />
      </motion.div>
    </motion.div>
  )
}
