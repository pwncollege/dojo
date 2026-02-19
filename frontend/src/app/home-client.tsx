'use client'

import Link from 'next/link'
import Image from 'next/image'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Loader2, AlertCircle, Star, Users, Trophy, BookOpen, Zap } from 'lucide-react'
import { Markdown } from '@/components/ui/markdown'
import { Belt } from '@/components/ui/belt'
import { DojoNinja } from '@/components/ui/dojo-ninja'
import { motion } from 'framer-motion'
import { useMemo } from 'react'

export interface Dojo {
  id: string
  name: string
  description?: string
  type: string
  official: boolean
  award?: {
    belt?: string
    emoji?: string
  }
  modules: number
  challenges: number
  active_hackers: number
}

interface HomePageClientProps {
  dojos: Dojo[]
}

export function HomePageClient({ dojos }: HomePageClientProps) {
  // Memoize computed values to prevent infinite re-renders
  const { gettingStartedDojos, coreDojos } = useMemo(() => {
    // Belt order for sorting
    const BELT_ORDER = ["white", "orange", "yellow", "green", "purple", "blue", "brown", "red", "black"]

    // Sort dojos by belt order for official dojos, then by name (create new array)
    const sortDojos = (dojoList: typeof dojos) => {
      return [...dojoList].sort((a, b) => {
        // If both have belts, sort by belt order
        if (a.award?.belt && b.award?.belt) {
          const aIndex = BELT_ORDER.indexOf(a.award.belt)
          const bIndex = BELT_ORDER.indexOf(b.award.belt)
          if (aIndex !== bIndex) {
            return aIndex - bIndex
          }
        }

        // If only one has a belt, prioritize the one with belt
        if (a.award?.belt && !b.award?.belt) return -1
        if (!a.award?.belt && b.award?.belt) return 1

        // Otherwise sort by name
        return (a.name || '').localeCompare(b.name || '')
      })
    }

    // Hardcoded dojo assignments to specific sections
    const gettingStartedDojoIds = [
      'computing-101',
      'linux-luminarium',
      'playing-with-programs',
      'start-here'
    ]

    const coreDojoIds = [
      'intro-to-cybersecurity',
      'system-security'
    ]

    // Categorize dojos by hardcoded lists
    const gettingStartedDojos = sortDojos(dojos.filter(dojo =>
      gettingStartedDojoIds.includes(dojo.id) ||
      (!coreDojoIds.includes(dojo.id)) // Include all non-core dojos in getting started
    ))

    const coreDojos = sortDojos(dojos.filter(dojo =>
      coreDojoIds.includes(dojo.id)
    ))

    return { gettingStartedDojos, coreDojos }
  }, [dojos])

  // Remove community section for now
  const communityDojos: typeof dojos = []

  const getDojoIcon = (dojo: any) => {
    // If dojo has an award with a belt, use the Belt component
    if (dojo.award?.belt && dojo.official) {
      return <Belt
        color={dojo.award.belt}
        alt={`${dojo.award.belt} belt`}
        className="h-6 w-auto max-w-[48px]"
      />
    }

    // If dojo has an award with an emoji, use the emoji
    if (dojo.award?.emoji) {
      return <span className="text-3xl">{dojo.award.emoji}</span>
    }

    // Fallback to name-based emojis
    const name = dojo.name?.toLowerCase() || ''
    if (name.includes('fundamentals')) return <span className="text-3xl">💻</span>
    if (name.includes('linux')) return <span className="text-3xl">🐧</span>
    if (name.includes('program')) return <span className="text-3xl">🔤</span>
    if (name.includes('web')) return <span className="text-3xl">🌐</span>
    if (name.includes('crypto')) return <span className="text-3xl">🔐</span>
    if (name.includes('reverse')) return <span className="text-3xl">🔍</span>
    if (name.includes('pwn')) return <span className="text-3xl">💥</span>
    if (name.includes('forensics')) return <span className="text-3xl">🕵️</span>
    return <span className="text-3xl">🎯</span>
  }

  const DojoCard = ({ dojo, progress = null }: { dojo: any, progress?: number | null }) => {
    // Don't render if dojo.id is missing
    if (!dojo.id) {
      return null
    }

    return (
    <Link href={`/dojo/${dojo.id}`} className="group">
      <Card className="relative h-full border border-border hover:border-primary/30 hover:bg-primary/5 transition-all duration-200 group-hover:translate-y-[-2px]">
        {/* Icon positioned top-right */}
        <div className="absolute top-4 right-4 flex items-center justify-center">
          {getDojoIcon(dojo)}
        </div>
        <CardHeader className="pb-3 pr-14">
          <CardTitle className="text-lg font-semibold truncate group-hover:text-foreground transition-colors mb-3">
            {dojo.name}
          </CardTitle>
          <div className="flex items-center gap-2 mb-3">
            {dojo.official && (
              <Badge variant="default" className="text-xs">
                Official
              </Badge>
            )}
            {progress !== null && (
              <Badge variant="outline" className="text-xs">
                {progress}%
              </Badge>
            )}
          </div>
        </CardHeader>

        <CardContent className="pt-0">
          {/* Progress Bar */}
          <div className="mb-4">
            <div className="flex items-center justify-between text-xs mb-2">
              <span className="text-muted-foreground">Progress</span>
              <span className="font-medium text-foreground">{progress || 0}%</span>
            </div>
            <div className="w-full bg-muted rounded-full h-2">
              <div
                className="bg-primary h-2 rounded-full transition-all duration-300"
                style={{ width: `${progress || 0}%` }}
              />
            </div>
          </div>

          {/* Stats Grid */}
          <div className="space-y-2 mb-4">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Modules</span>
              <span className="font-medium text-foreground">{dojo.modules || '-'}</span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Challenges</span>
              <span className="font-medium text-foreground">{dojo.challenges || '-'}</span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Active Hackers</span>
              <span className="font-medium text-foreground">{dojo.active_hackers || '-'}</span>
            </div>
          </div>

          {/* Action Indicator */}
          <div className="flex items-center justify-between pt-2 border-t border-border">
            <div className="text-xs text-muted-foreground">
              Explore course
            </div>
            <div className="text-xs text-muted-foreground group-hover:text-foreground transition-colors">
              →
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
    )
  }

  const SectionHeader = ({ icon, title, subtitle, description }: {
    icon: React.ReactNode,
    title: string,
    subtitle: string,
    description: string
  }) => (
    <div className="mb-12">
      <div className="flex items-center gap-3 mb-4">
        {icon}
        <h2 className="text-3xl font-bold">{title}</h2>
      </div>
      <p className="text-xl font-medium text-muted-foreground mb-2">{subtitle}</p>
      <p className="text-muted-foreground leading-relaxed">{description}</p>
    </div>
  )

  return (
    <motion.div
      className="min-h-screen bg-background text-foreground"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] }}
    >
        {/* Hero Section with Full Width Background */}
        <div className="relative">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16 sm:py-20 lg:py-24">
            <div className="relative grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
              <div className="max-w-4xl relative z-10">
                {/* Subtle backdrop with gradient for text visibility */}
                <div className="absolute -inset-8 bg-gradient-to-br from-background via-background/90 to-background/60 rounded-3xl" style={{ zIndex: -1 }} />

                <div className="relative z-10">
                  <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold mb-6 bg-gradient-to-r from-foreground to-muted-foreground bg-clip-text text-transparent">
                    Learn to Hack!
                  </h1>
                  <p className="text-muted-foreground text-lg sm:text-xl lg:text-2xl leading-relaxed mb-8 max-w-3xl">
                    The material is split into a number of "dojos", with each dojo typically covering a high-level topic.
                    The material is designed to be tackled in order.
                  </p>
                  <div className="text-sm sm:text-base text-muted-foreground">
                    {dojos.length} {dojos.length === 1 ? 'dojo' : 'dojos'} available
                  </div>
                </div>
              </div>
              <div className="flex justify-center lg:justify-end">
                <motion.div
                  initial={{ opacity: 0, scale: 0.8, y: 20 }}
                  animate={{
                    opacity: 1,
                    scale: 1,
                    y: 0
                  }}
                  transition={{
                    duration: 0.8,
                    ease: [0.25, 0.46, 0.45, 0.94]
                  }}
                  className="relative"
                >
                  <motion.div
                    animate={{
                      y: [0, -15, 0],
                      rotateZ: [0, 1, -1, 0]
                    }}
                    transition={{
                      duration: 6,
                      repeat: Infinity,
                      ease: "easeInOut"
                    }}
                  >
                    <DojoNinja
                      className="w-[400px] h-[400px] sm:w-80 sm:h-80 lg:w-[600px] lg:h-[600px] drop-shadow-2xl"
                      width={600}
                      height={600}
                      priority
                    />
                  </motion.div>
                </motion.div>
              </div>
            </div>
          </div>
        </div>

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          {/* Getting Started Section */}
          {gettingStartedDojos.length > 0 && (
            <div className="pt-16 sm:pt-20 pb-16 sm:pb-20">
              <SectionHeader
                icon={<Zap className="h-8 w-8 text-primary" />}
                title="Getting Started"
                subtitle="Learn the Basics!"
                description="These first few dojos are designed to help you Get Started with the platform. Start here before venturing onwards!"
              />
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {gettingStartedDojos.map((dojo) => (
                  <DojoCard key={dojo.id} dojo={dojo} progress={0} />
                ))}
              </div>
              <div className="mt-8 p-4 bg-muted/30 rounded-lg">
                <p className="text-muted-foreground font-medium">
                  After completing the dojos above, dive into the Core Material below!
                </p>
              </div>
            </div>
          )}

          {/* Core Material Section */}
          {coreDojos.length > 0 && (
            <div className="pb-16 sm:pb-20">
              <SectionHeader
                icon={<Trophy className="h-8 w-8 text-primary" />}
                title="Core Material"
                subtitle="Earn Your Belts!"
                description="These dojos form the official curriculum, taking you on a curated journey through the art of hacking. As you progress and build your skills, like in a martial art, you will earn belts for completing dojo after dojo."
              />
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {coreDojos.map((dojo) => (
                  <DojoCard key={dojo.id} dojo={dojo} />
                ))}
              </div>
            </div>
          )}

          {/* Community Material Section */}
          {communityDojos.length > 0 && (
            <div className="pb-16 sm:pb-20">
              <SectionHeader
                icon={<Users className="h-8 w-8 text-primary" />}
                title="Community Material"
                subtitle="Earn Badges!"
                description="No matter how much material we create, there is always more to learn! This section contains additional dojos created by the community. Some are designed to be tackled after you complete the dojos above, whereas others are open to anyone interested in more specialized topics."
              />
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {communityDojos.map((dojo) => (
                  <DojoCard key={dojo.id} dojo={dojo} />
                ))}
              </div>
            </div>
          )}

          {/* No Dojos State */}
          {dojos.length === 0 && (
            <div className="py-16">
              <BookOpen className="h-16 w-16 text-muted-foreground mb-4" />
              <h3 className="text-xl font-semibold mb-2">No dojos available yet</h3>
              <p className="text-muted-foreground">Check back soon for new challenges!</p>
            </div>
          )}
        </div>
    </motion.div>
  )
}
