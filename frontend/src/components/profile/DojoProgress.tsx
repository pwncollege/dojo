'use client'

import { Card } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Trophy } from 'lucide-react'
import Link from 'next/link'

interface DojoProgressItem {
  id: string
  name: string
  totalChallenges: number
  solvedChallenges: number
  slug: string
}

interface DojoProgressProps {
  dojos: DojoProgressItem[]
}

export function DojoProgress({ dojos }: DojoProgressProps) {
  if (!dojos || dojos.length === 0) {
    return (
      <Card className="p-6">
        <h2 className="text-lg font-semibold mb-4">Dojo Progress</h2>
        <p className="text-sm text-muted-foreground">No dojo progress to display</p>
      </Card>
    )
  }

  return (
    <Card className="p-6">
      <h2 className="text-lg font-semibold mb-4">Dojo Progress</h2>
      <div className="space-y-4">
        {dojos.map((dojo) => {
          const progress = dojo.totalChallenges > 0
            ? Math.round((dojo.solvedChallenges / dojo.totalChallenges) * 100)
            : 0

          return (
            <Link
              key={dojo.id}
              href={`/dojo/${dojo.slug}`}
              className="block p-4 rounded-lg hover:bg-muted/50 transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Trophy className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-medium text-sm">{dojo.name}</h3>
                </div>
                <span className="text-xs text-muted-foreground">
                  {dojo.solvedChallenges}/{dojo.totalChallenges}
                </span>
              </div>
              <Progress value={progress} className="h-2" />
              <p className="text-xs text-muted-foreground mt-1.5">
                {progress}% complete
              </p>
            </Link>
          )
        })}
      </div>
    </Card>
  )
}
