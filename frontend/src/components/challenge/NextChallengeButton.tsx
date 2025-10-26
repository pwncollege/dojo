'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ChevronRight, Loader2 } from 'lucide-react'
import { useUIStore, useWorkspaceStore } from '@/stores'
import { workspaceService } from '@/services/workspace'
import { useStartChallenge } from '@/hooks/useDojo'
import { cn } from '@/lib/utils'

export function NextChallengeButton() {
  const [loading, setLoading] = useState(false)
  const router = useRouter()
  const startChallenge = useStartChallenge()
  const setActiveChallenge = useWorkspaceStore(state => state.setActiveChallenge)

  const handleNextChallenge = async () => {
    try {
      setLoading(true)

      const response = await workspaceService.getNextChallenge()

      if (response.success && response.dojo && response.module && response.challenge) {
        const nextUrl = `/dojo/${response.dojo}/module/${response.module}/workspace/challenge/${response.challenge}`

        // Get current active challenge from store
        const currentChallenge = useWorkspaceStore.getState().activeChallenge

        // Check if we're switching to a different module
        if (currentChallenge && currentChallenge.moduleId !== response.module) {
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
      setLoading(false)
    }
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleNextChallenge}
          disabled={loading}
          className={cn(
            "h-9 px-3 gap-1.5 text-xs transition-all duration-200",
            "hover:bg-primary/10 hover:text-primary",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          {loading ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
          Next
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        <p>Go to next challenge</p>
      </TooltipContent>
    </Tooltip>
  )
}
