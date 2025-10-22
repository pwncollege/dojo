'use client'

import { useMemo, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useDojoStore, useWorkspaceStore } from '@/stores'
import { DojoWorkspaceLayout } from '@/components/layout/DojoWorkspaceLayout'
import { Loader2, AlertCircle, ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { Dojo, DojoModule } from '@/types/api'

interface WorkspacePageClientProps {
  dojo: Dojo
  module: DojoModule
  dojoId: string
  moduleId: string
  urlParams?: string[]
}

export function WorkspacePageClient({
  dojo,
  module,
  dojoId,
  moduleId,
  urlParams
}: WorkspacePageClientProps) {
  const router = useRouter()

  // Basic state access - only solves are available in client store now
  const solvesMap = useDojoStore(state => state.solves)
  const isLoading = useDojoStore(state => state.loadingSolves[`${dojoId}-all`])
  const error = useDojoStore(state => state.solveError[`${dojoId}-all`])

  // Simple data lookup
  const solves = solvesMap[`${dojoId}-all`] || []

  useEffect(() => {
    if (dojoId) {
      useDojoStore.getState().fetchSolves(dojoId)
    }
  }, [dojoId])

  // Get solved challenge IDs
  const solvedChallengeIds = new Set(
    solves
      ?.filter(solve => solve.module_id === moduleId)
      .map(solve => solve.challenge_id) || []
  )

  // Enrich module with solved status - memoized for stability
  const enrichedModule = useMemo(() => {
    return {
      ...module,
      challenges: module.challenges.map(challenge => ({
        ...challenge,
        solved: solvedChallengeIds.has(challenge.id)
      }))
    }
  }, [module, solvedChallengeIds])

  // Memoize event handlers to prevent unnecessary re-renders
  const handleChallengeStart = useMemo(() =>
    (dojoId: string, moduleId: string, challengeId: string) => {
      // Use window.history to update URL without triggering Next.js navigation
      const newUrl = `/dojo/${dojoId}/module/${moduleId}/workspace/challenge/${challengeId}`
      window.history.replaceState(null, '', newUrl)
    }, [router]
  )

  const handleResourceSelect = useMemo(() =>
    (resourceId: string | null) => {
      if (resourceId) {
        // Use window.history to update URL without triggering Next.js navigation
        const newUrl = `/dojo/${dojoId}/module/${moduleId}/workspace/resource/${resourceId}`
        window.history.replaceState(null, '', newUrl)
      } else {
        router.push(`/dojo/${dojoId}/module/${moduleId}`)
      }
    }, [router, dojoId, moduleId]
  )

  const handleChallengeClose = useMemo(() =>
    () => {
      // Minimize workspace instead of closing
      const { setMinimized } = useWorkspaceStore.getState()
      setMinimized(true)
    }, []
  )

  if (isLoading) {
    return (
      <div className="min-h-screen bg-background text-foreground p-6 flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
          <p>Loading workspace...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-background text-foreground p-6 flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
          <h1 className="text-2xl font-bold mb-4">Failed to load workspace</h1>
          <Button variant="outline" onClick={() => router.push('/')}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Dojos
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 w-full h-full z-40">
      <DojoWorkspaceLayout
        dojo={dojo}
        modules={[enrichedModule]}
        onChallengeStart={handleChallengeStart}
        onResourceSelect={handleResourceSelect}
        onChallengeClose={handleChallengeClose}
      />
    </div>
  )
}
