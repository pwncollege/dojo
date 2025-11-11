'use client'

import { useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useWorkspaceChallenge } from '@/stores'
import {
  Terminal,
  X,
  Maximize2,
  ChevronRight,
  AlertTriangle
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/lib/utils'

interface ActiveChallenge {
  dojoId: string
  moduleId: string
  challengeId: string
  challengeName: string
  dojoName: string
  moduleName: string
}

interface ActiveChallengeWidgetProps {
  activeChallenge?: ActiveChallenge | null
  onKillChallenge?: () => void
}

export function ActiveChallengeWidget({
  activeChallenge: propActiveChallenge,
  onKillChallenge
}: ActiveChallengeWidgetProps) {
  // Use workspace store as primary source, prop as fallback
  const { activeChallenge: storeActiveChallenge, setActiveChallenge } = useWorkspaceChallenge()
  const activeChallenge = storeActiveChallenge || propActiveChallenge
  const pathname = usePathname()
  const router = useRouter()
  const [isExpanded, setIsExpanded] = useState(false)
  const [isKilling, setIsKilling] = useState(false)

  // Don't show if no active challenge
  if (!activeChallenge) {
    return null
  }

  // Don't show if we're on any workspace page
  const isOnWorkspacePage = pathname.includes('/workspace/')

  if (isOnWorkspacePage) {
    return null
  }

  const handleGoToChallenge = () => {
    // Navigate to workspace URL (no scroll to preserve position)
    const challengePath = `/dojo/${activeChallenge.dojoId}/module/${activeChallenge.moduleId}/workspace/challenge/${activeChallenge.challengeId}`
    router.push(challengePath, { scroll: false })
  }

  const handleKillChallenge = async () => {
    if (!onKillChallenge) return

    setIsKilling(true)
    try {
      await onKillChallenge()
    } catch (error) {
      console.error('Failed to kill challenge:', error)
    } finally {
      setIsKilling(false)
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: 100, scale: 0.9 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 100, scale: 0.9 }}
        transition={{
          type: "spring",
          stiffness: 400,
          damping: 25,
          mass: 0.8
        }}
        className="fixed bottom-6 right-6 z-50"
      >
        <Card className={cn(
          "bg-background/95 backdrop-blur-sm border shadow-lg hover:shadow-xl transition-all duration-200",
          "max-w-sm"
        )}>
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              {/* Status indicator */}
              <div className="flex-shrink-0 mt-1">
                <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse" />
              </div>

              {/* Challenge info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <Terminal className="h-4 w-4 text-muted-foreground" />
                  <Badge variant="secondary" className="text-xs">
                    Active
                  </Badge>
                </div>

                <h4 className="font-semibold text-sm truncate mb-1">
                  {activeChallenge.challengeName}
                </h4>

                <p className="text-xs text-muted-foreground truncate">
                  {activeChallenge.dojoName} → {activeChallenge.moduleName}
                </p>

                {/* Action buttons */}
                <div className="flex items-center gap-2 mt-3">
                  <Button
                    size="sm"
                    onClick={handleGoToChallenge}
                    className="flex-1 h-8 text-xs"
                  >
                    <Maximize2 className="h-3 w-3 mr-1" />
                    Resume
                  </Button>

                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleKillChallenge}
                    disabled={isKilling}
                    className="h-8 px-2"
                    title="Stop challenge"
                  >
                    {isKilling ? (
                      <div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <X className="h-3 w-3" />
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.div>
    </AnimatePresence>
  )
}
