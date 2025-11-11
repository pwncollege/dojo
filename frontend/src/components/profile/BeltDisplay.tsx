'use client'

import { Belt } from '@/components/ui/belt'
import { Progress } from '@/components/ui/progress'
import { motion } from 'framer-motion'

interface BeltDisplayProps {
  belt: string
  progress: number
}

export function BeltDisplay({ belt, progress }: BeltDisplayProps) {
  const getNextBelt = (current: string) => {
    const order = ['white', 'yellow', 'orange', 'green', 'blue', 'purple', 'brown', 'black']
    const currentIndex = order.indexOf(current.toLowerCase())
    if (currentIndex === -1 || currentIndex === order.length - 1) return null
    return order[currentIndex + 1]
  }

  const nextBelt = getNextBelt(belt)

  return (
    <div className="space-y-4">
      <motion.div className="w-32 h-11 mx-auto">
        <Belt color={belt} className="w-full h-full" />
      </motion.div>

      <div className="text-center">
        <h3 className="text-2xl font-bold capitalize">{belt} Belt</h3>
      </div>

      {nextBelt && (
        <div className="space-y-1.5">
          <Progress value={progress} className="h-2" />
          <div className="text-xs text-muted-foreground text-center">
            <span>{progress}% to {nextBelt}</span>
          </div>
        </div>
      )}
    </div>
  )
}
