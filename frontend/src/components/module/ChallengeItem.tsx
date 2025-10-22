'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Markdown } from '@/components/ui/markdown'
import { StartChallengeButton } from '@/components/ui/start-challenge-button'
import { CheckCircle, Circle, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'

interface Challenge {
  id: string
  name: string
  required: boolean
  description?: string
  challenge_index?: number
  unified_index?: number
}

interface ChallengeItemProps {
  challenge: Challenge
  dojoId: string
  moduleId: string
  dojoName: string
  moduleName: string
  challengeIndex: number
  isSolved: boolean
  isInProgress: boolean
  isOpen: boolean
  onToggle: () => void
  headerOffset: number
}

export function ChallengeItem({
  challenge,
  dojoId,
  moduleId,
  dojoName,
  moduleName,
  challengeIndex,
  isSolved,
  isInProgress,
  isOpen,
  onToggle,
  headerOffset
}: ChallengeItemProps) {
  // Challenge status: solved > in progress > not started
  const status = isSolved ? 'solved' : isInProgress ? 'in-progress' : 'not-started'

  return (
    <Card
      className={cn(
        "hover:border-primary/50 transition-all duration-200 relative",
        isOpen && "border-primary/30",
        status === 'solved' && "border-primary/50 bg-primary/10",
        status === 'in-progress' && "border-amber-600/20 bg-amber-600/5"
      )}
    >
      <motion.div
        initial={false}
        className="relative"
        animate={status === 'in-progress' ? {
          scale: [1, 1.005, 1],
        } : {}}
        transition={{
          duration: 3,
          repeat: status === 'in-progress' ? Infinity : 0,
          ease: "easeInOut"
        }}
      >
        <CardHeader
          className={cn(
            "pb-3 pt-4 cursor-pointer group",
            isOpen && "sticky z-40 bg-card rounded-t-xl border-b shadow-sm transition-all duration-300"
          )}
          style={{
            top: isOpen ? `${headerOffset * 0.25}rem` : undefined,
            transition: 'top 0.3s ease-out'
          }}
          onClick={onToggle}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <motion.div
                className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-sm font-medium text-primary flex-shrink-0"
                animate={{
                  scale: isOpen ? 1.05 : 1,
                  backgroundColor: isOpen ? "hsl(var(--primary) / 0.15)" : "hsl(var(--primary) / 0.1)"
                }}
                transition={{ duration: 0.2 }}
              >
                {challengeIndex + 1}
              </motion.div>
              <div className="flex items-center gap-2">
                <motion.div
                  animate={{
                    rotate: status === 'solved' ? 0 : 0,
                    scale: status === 'in-progress' ? [1, 1.1, 1] : 1
                  }}
                  transition={{
                    duration: 0.2,
                    scale: { duration: 1.5, repeat: status === 'in-progress' ? Infinity : 0 }
                  }}
                >
                  {status === 'solved' ? (
                    <CheckCircle className="h-4 w-4 text-primary" />
                  ) : status === 'in-progress' ? (
                    <Clock className="h-4 w-4 text-amber-600" />
                  ) : (
                    <Circle className="h-4 w-4 text-muted-foreground" />
                  )}
                </motion.div>
                <CardTitle className="text-lg group-hover:text-primary transition-colors">
                  {challenge.name}
                </CardTitle>
                <div className="flex items-center gap-2 ml-2">
                  {!challenge.required && (
                    <Badge variant="secondary" className="text-xs">Optional</Badge>
                  )}
                  {status === 'solved' && (
                    <Badge variant="default" className="text-xs bg-primary/10 text-primary border-primary/20">
                      Solved
                    </Badge>
                  )}
                  {status === 'in-progress' && (
                    <Badge variant="default" className="text-xs bg-amber-600/10 text-amber-700 border-amber-600/20">
                      In Progress
                    </Badge>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <motion.div
                animate={{
                  opacity: isOpen ? 1 : 0,
                  x: isOpen ? 0 : 10
                }}
                transition={{ duration: 0.2 }}
                className="group-hover:!opacity-100 group-hover:!x-0"
              >
                <StartChallengeButton
                  dojoId={dojoId}
                  moduleId={moduleId}
                  challengeId={challenge.id}
                  challengeName={challenge.name}
                  dojoName={dojoName}
                  moduleName={moduleName}
                  isSolved={isSolved}
                  size="sm"
                />
              </motion.div>
            </div>
          </div>
        </CardHeader>

        <AnimatePresence initial={false}>
          {isOpen && (
            <motion.div
              key={`content-${challenge.id}`}
              initial={{ height: 0, opacity: 0 }}
              animate={{
                height: "auto",
                opacity: 1,
                transition: {
                  height: { duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] },
                  opacity: { duration: 0.2, delay: 0.1 }
                }
              }}
              exit={{
                height: 0,
                opacity: 0,
                transition: {
                  height: { duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] },
                  opacity: { duration: 0.1 }
                }
              }}
              style={{ overflow: "hidden" }}
            >
              <CardContent className="border-t">
                <motion.div
                  initial={{ y: -10, opacity: 0 }}
                  animate={{ y: 0, opacity: 1 }}
                  exit={{ y: -10, opacity: 0 }}
                  transition={{ duration: 0.2, delay: 0.1 }}
                >
                  {challenge.description && (
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <Markdown>{challenge.description}</Markdown>
                    </div>
                  )}
                </motion.div>
              </CardContent>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </Card>
  )
}