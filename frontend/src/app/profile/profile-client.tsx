'use client'

import { motion } from 'framer-motion'
import { Trophy } from 'lucide-react'
import { Belt } from '@/components/ui/belt'
import { BeltDisplay } from '@/components/profile/BeltDisplay'
import { RecentActivity } from '@/components/profile/RecentActivity'
import { DojoProgress } from '@/components/profile/DojoProgress'
import { SocialShareButtons } from '@/components/profile/SocialShareButtons'
import { ActivityHeatmap } from '@/components/profile/ActivityHeatmap'

interface User {
  username: string
  email: string
}

interface Stats {
  belt: string
  beltProgress: number
  rank: number
}

interface DayActivity {
  date: string
  count: number
}

interface ProfileClientProps {
  user: User
  stats: Stats
  recentActivity: any[]
  dojoProgress: any[]
  activityData: DayActivity[]
}

const getNextBelt = (current: string) => {
  const order = ['white', 'yellow', 'orange', 'green', 'blue', 'purple', 'brown', 'black']
  const currentIndex = order.indexOf(current.toLowerCase())
  if (currentIndex === -1 || currentIndex === order.length - 1) return null
  return order[currentIndex + 1]
}

export function ProfileClient({ user, stats, recentActivity, dojoProgress, activityData }: ProfileClientProps) {
  const nextBelt = getNextBelt(stats.belt)

  return (
    <div className="min-h-screen">
      {/* Header Section */}
      <div className="bg-card border-b">
        <div className="container max-w-7xl mx-auto px-6 py-12">
          <div className="flex items-center justify-between gap-12">
            {/* Left side: User info */}
            <motion.div
              className="flex-1 space-y-6"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4 }}
            >
              <div>
                <h1 className="text-4xl font-bold tracking-tight mb-1">
                  {user.username}
                </h1>
                <p className="text-sm text-muted-foreground">{user.email}</p>
              </div>

              <div className="flex items-center gap-6">
                <div className="flex items-center gap-2">
                  <Trophy className="h-4 w-4 text-muted-foreground" />
                  <span className="text-xl font-bold font-mono">#{stats.rank}</span>
                </div>

                <div className="flex items-center gap-2">
                  <div className="w-16 h-5">
                    <Belt color={stats.belt} className="w-full h-full" />
                  </div>
                  <span className="text-sm text-muted-foreground">
                    {stats.beltProgress}% to {nextBelt || 'max'}
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <SocialShareButtons username={user.username} />
              </div>
            </motion.div>
          </div>
        </div>
      </div>

      {/* Content Section */}
      <div className="container max-w-7xl mx-auto px-6 py-8">
        <div className="space-y-6">
          {/* Activity Heatmap - Full Width */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.1 }}
          >
            <ActivityHeatmap activities={activityData} />
          </motion.div>

          {/* Two Column Layout */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.2 }}
            >
              <RecentActivity activities={recentActivity} />
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.3 }}
            >
              <DojoProgress dojos={dojoProgress} />
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  )
}
