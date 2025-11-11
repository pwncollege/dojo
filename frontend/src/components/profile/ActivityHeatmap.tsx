'use client'

import { Card } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

interface DayActivity {
  date: string
  count: number
}

interface ActivityHeatmapProps {
  activities: DayActivity[]
}

export function ActivityHeatmap({ activities }: ActivityHeatmapProps) {
  // Generate last 365 days
  const generateDays = () => {
    const days: DayActivity[] = []
    const today = new Date()

    for (let i = 364; i >= 0; i--) {
      const date = new Date(today)
      date.setDate(date.getDate() - i)
      const dateString = date.toISOString().split('T')[0]

      const activity = activities.find(a => a.date === dateString)
      days.push({
        date: dateString,
        count: activity?.count || 0
      })
    }

    return days
  }

  // Group days by week
  const groupByWeeks = (days: DayActivity[]) => {
    const weeks: DayActivity[][] = []
    let currentWeek: DayActivity[] = []

    // Pad beginning to start on Sunday
    const firstDay = new Date(days[0].date)
    const dayOfWeek = firstDay.getDay()
    for (let i = 0; i < dayOfWeek; i++) {
      currentWeek.push({ date: '', count: 0 })
    }

    days.forEach((day, index) => {
      currentWeek.push(day)

      if (currentWeek.length === 7 || index === days.length - 1) {
        // Pad end of last week
        while (currentWeek.length < 7) {
          currentWeek.push({ date: '', count: 0 })
        }
        weeks.push(currentWeek)
        currentWeek = []
      }
    })

    return weeks
  }

  const getIntensityClass = (count: number) => {
    if (count === 0) return 'bg-muted/30'
    if (count <= 2) return 'bg-primary/30'
    if (count <= 5) return 'bg-primary/50'
    if (count <= 10) return 'bg-primary/70'
    return 'bg-primary'
  }

  const days = generateDays()
  const weeks = groupByWeeks(days)
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const weekDays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

  const formatDate = (dateString: string) => {
    if (!dateString) return ''
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  const totalSolves = activities.reduce((sum, day) => sum + day.count, 0)
  const currentStreak = () => {
    let streak = 0
    for (let i = days.length - 1; i >= 0; i--) {
      if (days[i].count > 0) {
        streak++
      } else if (streak > 0) {
        break
      }
    }
    return streak
  }

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">Activity</h2>
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <div>
            <span className="font-semibold text-foreground">{totalSolves}</span> solves this year
          </div>
          <div>
            <span className="font-semibold text-foreground">{currentStreak()}</span> day streak
          </div>
        </div>
      </div>

      <TooltipProvider>
        <div className="overflow-x-auto">
          <div className="inline-flex gap-1">
            {weeks.map((week, weekIndex) => (
              <div key={weekIndex} className="flex flex-col gap-1">
                {week.map((day, dayIndex) => (
                  <Tooltip key={`${weekIndex}-${dayIndex}`}>
                    <TooltipTrigger asChild>
                      <div
                        className={cn(
                          'w-3 h-3 rounded-sm transition-all hover:ring-2 hover:ring-primary/50',
                          day.date ? getIntensityClass(day.count) : 'bg-transparent'
                        )}
                      />
                    </TooltipTrigger>
                    {day.date && (
                      <TooltipContent>
                        <p className="font-medium">
                          {day.count} {day.count === 1 ? 'solve' : 'solves'}
                        </p>
                        <p className="text-xs text-muted-foreground">{formatDate(day.date)}</p>
                      </TooltipContent>
                    )}
                  </Tooltip>
                ))}
              </div>
            ))}
          </div>
        </div>
      </TooltipProvider>

      {/* Legend */}
      <div className="flex items-center gap-2 mt-4 text-xs text-muted-foreground">
        <span>Less</span>
        <div className="flex gap-1">
          <div className="w-3 h-3 rounded-sm bg-muted/30" />
          <div className="w-3 h-3 rounded-sm bg-primary/30" />
          <div className="w-3 h-3 rounded-sm bg-primary/50" />
          <div className="w-3 h-3 rounded-sm bg-primary/70" />
          <div className="w-3 h-3 rounded-sm bg-primary" />
        </div>
        <span>More</span>
      </div>
    </Card>
  )
}
