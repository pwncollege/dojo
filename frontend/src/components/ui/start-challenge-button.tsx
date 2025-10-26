'use client'

import React, { startTransition } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Play, Loader2 } from 'lucide-react'
import { useStartChallenge } from '@/hooks/useDojo'
import { useWorkspaceChallenge, useAuthStore, useWorkspaceStore } from '@/stores'
import { cn } from '@/lib/utils'

interface StartChallengeButtonProps {
  dojoId: string
  moduleId: string
  challengeId: string
  challengeName?: string
  dojoName?: string
  moduleName?: string
  isSolved?: boolean
  variant?: 'default' | 'outline' | 'ghost' | 'secondary'
  size?: 'default' | 'sm' | 'lg'
  className?: string
  practice?: boolean
  children?: React.ReactNode
  onClick?: (e: React.MouseEvent) => void
}

export function StartChallengeButton({
  dojoId,
  moduleId,
  challengeId,
  challengeName,
  dojoName,
  moduleName,
  isSolved = false,
  variant = 'default',
  size = 'default',
  className,
  practice = false,
  children,
  onClick
}: StartChallengeButtonProps) {
  const router = useRouter()
  const pathname = usePathname()
  const startChallengeMutation = useStartChallenge()
  const { setActiveChallenge } = useWorkspaceChallenge()
  const isAuthenticated = useAuthStore(state => state.isAuthenticated)

  const handleStart = async (e: React.MouseEvent) => {
    e.stopPropagation()

    // Call custom onClick if provided
    if (onClick) {
      onClick(e)
    }

    // Check authentication first
    if (!isAuthenticated) {
      router.push('/login')
      return
    }

    // 1. Update state immediately for instant UI feedback
    setActiveChallenge({
      dojoId,
      moduleId,
      challengeId,
      challengeName: challengeName || challengeId,
      dojoName: dojoName || dojoId,
      moduleName: moduleName || moduleId,
      isStarting: true
    })

    // 2. Navigate to workspace URL
    router.push(`/dojo/${dojoId}/module/${moduleId}/workspace/challenge/${challengeId}`)

    // 3. Start the challenge on the server in background
    // The workspace will show loading until this completes
    startChallengeMutation.mutateAsync({
      dojoId,
      moduleId,
      challengeId,
      practice
    }).then(() => {
      // Update the active challenge to remove isStarting flag
      setActiveChallenge({
        dojoId,
        moduleId,
        challengeId,
        challengeName: challengeName || challengeId,
        dojoName: dojoName || dojoId,
        moduleName: moduleName || moduleId,
        isStarting: false
      })
    }).catch((error) => {
      console.error('Failed to start challenge:', error)
      // Still remove isStarting flag on error
      setActiveChallenge({
        dojoId,
        moduleId,
        challengeId,
        challengeName: challengeName || challengeId,
        dojoName: dojoName || dojoId,
        moduleName: moduleName || moduleId,
        isStarting: false
      })
    })
  }

  const isLoading = false // No loading state - navigate immediately

  return (
    <Button
      onClick={handleStart}
      size={size}
      variant={isSolved ? 'outline' : variant}
      disabled={isLoading}
      className={cn(className)}
    >
      {isLoading ? (
        <Loader2 className="h-3 w-3 animate-spin mr-1" />
      ) : (
        <Play className="h-3 w-3 mr-1" />
      )}
      {children || (isSolved ? 'Review' : 'Start')}
    </Button>
  )
}