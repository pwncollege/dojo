'use client'

import { useState, useEffect, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useDojoStore, useAuthStore } from '@/stores'
import { Markdown } from '@/components/ui/markdown'
import { Belt } from '@/components/ui/belt'
import { ArrowLeft, BookOpen, Users, Trophy, Target, ChevronRight, Activity, Zap } from 'lucide-react'
import { motion } from 'framer-motion'

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
  stats?: {
    users: number
    challenges: number
    visible_challenges: number
    solves: number
    recent_solves: Array<{
      challenge_name: string
      date: string
      date_display: string
    }>
    trends: {
      solves: number
      users: number
      active: number
      challenges: number
    }
    chart_data: {
      labels: string[]
      solves: number[]
      users: number[]
    }
  }
}

interface DojoPageClientProps {
  dojo: DojoDetail
  dojoId: string
}

export function DojoPageClient({ dojo, dojoId }: DojoPageClientProps) {
  const router = useRouter()
  const [isDescriptionExpanded, setIsDescriptionExpanded] = useState(false)

  // Auth state
  const isAuthenticated = useAuthStore(state => state.isAuthenticated)

  // Get solves from store (will be empty initially for server-rendered page)
  const solvesMap = useDojoStore(state => state.solves)
  const solves = solvesMap[`${dojoId}-all`] || []

  // Use real stats from API, with fallback to calculated values
  const stats = useMemo(() => ({
    totalChallenges: dojo.stats?.challenges || dojo.modules.reduce((acc, mod) => acc + (mod.challenges?.length || 0), 0),
    totalSolves: dojo.stats?.solves || solves.length,
    uniqueHackers: dojo.stats?.users || new Set(solves.map(solve => solve.user_id)).size,
    hackingNow: dojo.stats?.trends?.active || 0
  }), [dojo.modules, dojo.stats, solves])

  useEffect(() => {
    // Only fetch solves if user is authenticated
    if (isAuthenticated) {
      useDojoStore.getState().fetchSolves(dojoId)
    }
  }, [dojoId, isAuthenticated])

  // Create a set of solved challenge IDs for quick lookup
  const solvedChallengeIds = new Set(solves.map(solve => solve.challenge_id))

  const getDojoIcon = (dojo: DojoDetail) => {
    // If dojo has an award with a belt, use the Belt component
    if (dojo?.award?.belt && dojo.official) {
      return <Belt
        color={dojo.award.belt}
        className="h-8 w-auto max-w-[72px]"
      />
    }

    // If dojo has an award with an emoji, use the emoji
    if (dojo?.award?.emoji) {
      return <span className="text-5xl">{dojo.award.emoji}</span>
    }

    // Fallback to name-based emojis
    const name = dojo?.name?.toLowerCase() || ''
    if (name.includes('fundamentals')) return <span className="text-5xl">💻</span>
    if (name.includes('linux')) return <span className="text-5xl">🐧</span>
    if (name.includes('program')) return <span className="text-5xl">🔤</span>
    if (name.includes('web')) return <span className="text-5xl">🌐</span>
    if (name.includes('crypto')) return <span className="text-5xl">🔐</span>
    if (name.includes('reverse')) return <span className="text-5xl">🔍</span>
    if (name.includes('pwn')) return <span className="text-5xl">💥</span>
    if (name.includes('forensics')) return <span className="text-5xl">🕵️</span>
    return <span className="text-5xl">🎯</span>
  }

  return (
    <motion.div
      className="min-h-screen bg-background text-foreground"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] }}
    >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {/* Header */}
          <div className="flex items-center gap-4 mb-8">
            <Button variant="ghost" size="sm" onClick={() => router.push('/')}>
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Dojos
            </Button>
          </div>

          {/* Course Hero Section */}
          <div className="mb-12 relative">
            {/* Icon positioned top-right */}
            <div className="absolute top-0 right-0 flex items-center justify-center">
              {getDojoIcon(dojo)}
            </div>

            <div className="pr-16">
              <h1 className="text-3xl sm:text-4xl font-bold mb-3">{dojo?.name || dojoId}</h1>
              <div className="flex items-center gap-3 mb-4">
                {dojo?.official && (
                  <Badge variant="default">Official</Badge>
                )}
                <Badge variant="outline">
                  {stats.totalSolves} Total Solves
                </Badge>
                <Badge variant="secondary">
                  {dojo.modules.length} {dojo.modules.length === 1 ? 'Module' : 'Modules'}
                </Badge>
              </div>

              {dojo?.description && (
                <div className="text-lg text-muted-foreground leading-relaxed max-w-3xl">
                  <div className="relative">
                    <div
                      className={`transition-all duration-300 ${
                        !isDescriptionExpanded ? 'max-h-24 overflow-hidden' : ''
                      }`}
                    >
                      <Markdown className="text-lg">{dojo.description}</Markdown>
                    </div>

                    {!isDescriptionExpanded && dojo.description.length > 200 && (
                      <div className="absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-background to-transparent pointer-events-none" />
                    )}

                    {dojo.description.length > 200 && (
                      <button
                        onClick={() => setIsDescriptionExpanded(!isDescriptionExpanded)}
                        className="mt-2 text-primary hover:text-primary/80 text-sm font-medium transition-colors"
                      >
                        {isDescriptionExpanded ? 'Show less' : 'Read more'}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Course Stats Section */}
          <div className="mb-8">
            <h2 className="text-xl font-bold mb-6 flex items-center gap-2">
              <Activity className="h-5 w-5 text-primary" />
              Course Statistics
            </h2>

            <div className="bg-gradient-to-br from-background via-background to-muted/20 rounded-xl border border-border/50 p-6 backdrop-blur-sm">
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
                {/* Total Solves */}
                <div className="group">
                  <div className="flex items-center gap-3 mb-2">
                    <div className="w-10 h-10 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
                      <Trophy className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <div className="text-2xl font-bold tracking-tight text-foreground">{stats.totalSolves.toLocaleString()}</div>
                      <div className="text-sm font-medium text-muted-foreground">Total Solves</div>
                    </div>
                  </div>
                </div>

                {/* Hacking Now */}
                <div className="group">
                  <div className="flex items-center gap-3 mb-2">
                    <div className="w-10 h-10 rounded-lg bg-green-500/10 border border-green-500/20 flex items-center justify-center group-hover:bg-green-500/20 transition-colors">
                      <div className="relative">
                        <Zap className="h-5 w-5 text-green-600" />
                        <div className="absolute -top-1 -right-1 w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                      </div>
                    </div>
                    <div>
                      <div className="text-2xl font-bold tracking-tight text-foreground">{stats.hackingNow}</div>
                      <div className="text-sm font-medium text-muted-foreground">Hacking Now</div>
                    </div>
                  </div>
                </div>

                {/* Total Challenges */}
                <div className="group">
                  <div className="flex items-center gap-3 mb-2">
                    <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center group-hover:bg-blue-500/20 transition-colors">
                      <Target className="h-5 w-5 text-blue-600" />
                    </div>
                    <div>
                      <div className="text-2xl font-bold tracking-tight text-foreground">{stats.totalChallenges}</div>
                      <div className="text-sm font-medium text-muted-foreground">Challenges</div>
                    </div>
                  </div>
                </div>

                {/* Unique Hackers */}
                <div className="group">
                  <div className="flex items-center gap-3 mb-2">
                    <div className="w-10 h-10 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center group-hover:bg-purple-500/20 transition-colors">
                      <Users className="h-5 w-5 text-purple-600" />
                    </div>
                    <div>
                      <div className="text-2xl font-bold tracking-tight text-foreground">{stats.uniqueHackers}</div>
                      <div className="text-sm font-medium text-muted-foreground">Unique Hackers</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Modules Grid */}
          <div className="space-y-6">
            <h2 className="text-2xl font-bold mb-6 flex items-center gap-2">
              <BookOpen className="h-6 w-6 text-primary" />
              Course Modules
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              {dojo.modules.map((module, index) => {
                const moduleProgress = module.challenges ?
                  module.challenges.filter(c => solvedChallengeIds.has(c.id)).length / module.challenges.length * 100 : 0

                return (
                  <Card key={module.id} className="h-full hover:border-muted-foreground/20 transition-all duration-200 hover:translate-y-[-2px] hover:shadow-md">
                    {/* Module Card Header */}
                    <CardHeader className="pb-3">
                      <div className="flex items-start gap-3">
                        <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-sm font-semibold text-primary flex-shrink-0">
                          {index + 1}
                        </div>
                        <div className="flex-1 min-w-0">
                          <CardTitle className="text-lg mb-2 leading-tight">{module.name}</CardTitle>
                          <div className="flex items-center gap-2 mb-3">
                            <Badge variant="outline" className="text-xs">
                              {Math.round(moduleProgress)}% Complete
                            </Badge>
                            <Badge variant="secondary" className="text-xs">
                              {module.challenges?.length || 0} challenges
                            </Badge>
                          </div>
                        </div>
                      </div>
                    </CardHeader>

                    {/* Module Card Content */}
                    <CardContent className="pt-0">
                      {/* Progress Bar */}
                      <div className="mb-4">
                        <div className="flex items-center justify-between text-xs mb-2">
                          <span className="text-muted-foreground">Progress</span>
                          <span className="font-medium">
                            {module.challenges?.filter(c => solvedChallengeIds.has(c.id)).length || 0} / {module.challenges?.length || 0}
                          </span>
                        </div>
                        <div className="w-full bg-muted rounded-full h-2">
                          <div
                            className="bg-primary h-2 rounded-full transition-all duration-300"
                            style={{ width: `${moduleProgress}%` }}
                          />
                        </div>
                      </div>

                      {/* View Challenges Button */}
                      <Button
                        asChild
                        variant="outline"
                        size="sm"
                        className="w-full"
                      >
                        <Link href={`/dojo/${dojoId}/module/${module.id}`}>
                          View Challenges
                          <ChevronRight className="h-4 w-4 ml-2" />
                        </Link>
                      </Button>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </div>

          {/* Leaderboard Section */}
          <div className="mt-12">
            <h2 className="text-2xl font-bold mb-6 flex items-center gap-2">
              <Users className="h-6 w-6 text-primary" />
              Leaderboard
            </h2>

            <Card className="relative overflow-hidden hover:border-muted-foreground/20 transition-all duration-300">
              <div className="absolute inset-0 bg-gradient-to-br from-accent/5 to-transparent" />
              <CardContent className="relative p-6 space-y-6">
                {/* Your Rank */}
                <div className="p-4 bg-accent/10 rounded-lg text-center">
                  <div className="text-sm text-muted-foreground mb-1">Your Rank</div>
                  <div className="text-3xl font-bold text-accent">-</div>
                  <div className="text-xs text-muted-foreground mt-1">Not ranked yet</div>
                </div>

                {/* Top Performers */}
                <div className="space-y-2">
                  <div className="text-sm font-medium text-muted-foreground">Top Performers</div>
                  <div className="space-y-2">
                    {[1, 2, 3].map((rank) => (
                      <div key={rank} className="flex items-center justify-between p-2 rounded-lg bg-muted/50">
                        <div className="flex items-center gap-2">
                          <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center text-xs font-bold">
                            {rank}
                          </div>
                          <span className="text-sm text-muted-foreground">-</span>
                        </div>
                        <span className="text-sm font-medium text-muted-foreground">- pts</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Action Button */}
                <Button variant="outline" className="w-full" asChild>
                  <Link href="/leaderboard">View Full Leaderboard</Link>
                </Button>
              </CardContent>
            </Card>
          </div>
      </div>
    </motion.div>
  )
}