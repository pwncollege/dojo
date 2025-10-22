'use client'

import React, { startTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Play, BookOpen, Video, Loader2 } from 'lucide-react'
import { useAuthStore } from '@/stores'
import { cn } from '@/lib/utils'

interface StartResourceButtonProps {
  dojoId: string
  moduleId: string
  resourceId: string
  resourceType?: 'lecture' | 'markdown' | 'header'
  variant?: 'default' | 'outline' | 'ghost' | 'secondary'
  size?: 'default' | 'sm' | 'lg'
  className?: string
  children?: React.ReactNode
  onClick?: (e: React.MouseEvent) => void
}

export function StartResourceButton({
  dojoId,
  moduleId,
  resourceId,
  resourceType = 'markdown',
  variant = 'default',
  size = 'default',
  className,
  children,
  onClick
}: StartResourceButtonProps) {
  const router = useRouter()
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

    // Navigate to resource workspace
    startTransition(() => {
      router.push(`/dojo/${dojoId}/module/${moduleId}/workspace/resource/${resourceId}`)
    })
  }

  // Determine icon based on resource type
  const getIcon = () => {
    if (resourceType === 'lecture') {
      return <Video className="h-3 w-3 mr-1" />
    }
    return <BookOpen className="h-3 w-3 mr-1" />
  }

  const isLoading = false // No loading state - navigate immediately

  return (
    <Button
      onClick={handleStart}
      size={size}
      variant={variant}
      disabled={isLoading}
      className={cn(className)}
    >
      {isLoading ? (
        <Loader2 className="h-3 w-3 animate-spin mr-1" />
      ) : (
        getIcon()
      )}
      {children || 'Start Learning'}
    </Button>
  )
}