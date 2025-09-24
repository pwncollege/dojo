'use client'

import { useState, useRef, useEffect } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Markdown } from '@/components/ui/markdown'
import { StartChallengeButton } from '@/components/ui/start-challenge-button'
import { StartResourceButton } from '@/components/ui/start-resource-button'
import { useDojoStore, useHeaderState, useUIStore, useAuthStore } from '@/stores'
import { ArrowLeft, CheckCircle, Circle, Clock, FileText, Video, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'

interface Module {
  id: string
  name: string
  description?: string
  resources?: Array<{
    id: string
    name: string
    type: 'markdown' | 'lecture' | 'header'
    content?: string
    video?: string
    playlist?: string
    slides?: string
    expandable?: boolean
  }>
  challenges: Array<{
    id: string
    name: string
    required: boolean
    description?: string
  }>
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
  const router = useRouter()
  const { isHeaderHidden } = useHeaderState()

  // State for challenge accordion (only one open at a time) - MUST be at the top
  const [openChallenge, setOpenChallenge] = useState<string | null>(null)
  const [headerOffset, setHeaderOffset] = useState(16) // Dynamic offset based on header position
  const [lastScrollY, setLastScrollY] = useState(0)

  // Direct state access to avoid selector issues
  const solvesMap = useDojoStore(state => state.solves)
  const activeChallenge = useUIStore(state => state.activeChallenge)

  // Auth state
  const isAuthenticated = useAuthStore(state => state.isAuthenticated)

  // Get solves from store (will be empty initially for server-rendered page)
  const solves = solvesMap[`${dojoId}-all`] || []

  useEffect(() => {
    // Only fetch solves if user is authenticated
    if (isAuthenticated) {
      useDojoStore.getState().fetchSolves(dojoId)
    }
  }, [dojoId, isAuthenticated])

  // Track header position and calculate dynamic offset - match Header.tsx logic exactly
  useEffect(() => {
    const handleScroll = () => {
      const currentScrollY = window.scrollY

      // If HeaderContext says header is hidden, offset is 0
      if (isHeaderHidden) {
        setHeaderOffset(0)
        setLastScrollY(currentScrollY)
        return
      }

      // Match the exact header hide/show logic from Header.tsx
      if (currentScrollY > lastScrollY && currentScrollY > 100) {
        // Scrolling down and past threshold - header hidden
        setHeaderOffset(0)
      } else if (currentScrollY < lastScrollY) {
        // Scrolling up - header visible
        setHeaderOffset(16)
      }
      // If scrollY === lastScrollY, keep current offset

      setLastScrollY(currentScrollY)
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [lastScrollY, isHeaderHidden])

  // Get solved challenge IDs for this module
  // Note: solves are already filtered by dojo when fetched, so we only need to filter by module
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

            {module.resources && module.resources.length > 0 && (
              <div className="mt-12">
                <h2 className="text-2xl font-bold mb-6">Learning Materials</h2>
                <div className="space-y-3">
                  {module.resources
                    .filter(resource => resource.type === 'lecture' || resource.type === 'markdown')
                    .map((resource, index) => {
                    const isOpen = openChallenge === `resource-${index}`

                    return (
                      <Card key={resource.id} className={cn(
                        "hover:border-primary/50 transition-all duration-200",
                        isOpen && "border-primary/30"
                      )}>
                        <CardHeader
                          className="pb-3 pt-4 cursor-pointer group"
                          onClick={() => setOpenChallenge(isOpen ? null : `resource-${index}`)}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-3">
                              {resource.type === 'lecture' ? (
                                <Video className="h-5 w-5 text-primary" />
                              ) : (
                                <FileText className="h-5 w-5 text-primary" />
                              )}
                              <CardTitle className="text-lg group-hover:text-primary transition-colors">
                                {resource.name}
                              </CardTitle>
                              {resource.type === 'lecture' && resource.video && (
                                <Badge variant="secondary" className="text-xs">Video</Badge>
                              )}
                              {resource.type === 'lecture' && resource.slides && (
                                <Badge variant="secondary" className="text-xs">Slides</Badge>
                              )}
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
                                <StartResourceButton
                                  dojoId={dojoId!}
                                  moduleId={moduleId!}
                                  resourceId={resource.id}
                                  resourceType={resource.type}
                                  size="sm"
                                  className="gap-2"
                                />
                              </motion.div>
                              <ChevronRight className={cn(
                                "h-5 w-5 text-muted-foreground transition-transform duration-200",
                                isOpen && "rotate-90"
                              )} />
                            </div>
                          </div>
                        </CardHeader>

                        <AnimatePresence initial={false}>
                          {isOpen && (
                            <motion.div
                              key={`resource-content-${resource.id}`}
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
                                  {resource.type === 'lecture' && resource.video && (
                                    <div className="mb-4 mt-5">
                                      <div className="aspect-video w-full">
                                        <iframe
                                          src={`https://www.youtube.com/embed/${resource.video}${resource.playlist ? `?list=${resource.playlist}` : ''}?rel=0`}
                                          className="w-full h-full rounded-lg"
                                          title="YouTube video player"
                                          allowFullScreen
                                        />
                                      </div>
                                    </div>
                                  )}
                                  {resource.type === 'lecture' && resource.slides && (
                                    <div className="">
                                      <div className="aspect-video w-full">
                                        <iframe
                                          src={`https://docs.google.com/presentation/d/${resource.slides}/embed`}
                                          className="w-full h-full rounded-lg"
                                          allowFullScreen
                                        />
                                      </div>
                                    </div>
                                  )}
                                  {resource.type === 'markdown' && resource.content && (
                                    <div className="prose prose-sm dark:prose-invert max-w-none">
                                      <Markdown>{resource.content}</Markdown>
                                    </div>
                                  )}
                                </motion.div>
                              </CardContent>
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </Card>
                    )
                  })}
                </div>
              </div>
            )}

            <div className="mt-12">
              <h2 className="text-2xl font-bold mb-6">Challenges</h2>
              <div className="space-y-3">
                {module.challenges.map((challenge, index) => {
                  const isSolved = solvedChallengeIds.has(challenge.id)
                  const isInProgress = activeChallenge &&
                    activeChallenge.dojoId === dojoId &&
                    activeChallenge.moduleId === moduleId &&
                    activeChallenge.challengeId === challenge.id
                  const isOpen = openChallenge === challenge.id

                  // Challenge status: solved > in progress > not started
                  const status = isSolved ? 'solved' : isInProgress ? 'in-progress' : 'not-started'

                  return (
                    <Card
                      key={challenge.id}
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
                          onClick={() => setOpenChallenge(isOpen ? null : challenge.id)}
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
                                {index + 1}
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
                                <CardTitle className="text-lg group-hover:text-primary transition-colors">{challenge.name}</CardTitle>
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
                                  dojoId={dojoId!}
                                  moduleId={moduleId!}
                                  challengeId={challenge.id}
                                  challengeName={challenge.name}
                                  dojoName={dojo.name}
                                  moduleName={module.name}
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
                })}
              </div>
            </div>

          </div>
        </div>
      </motion.div>
  )
}