import Link from 'next/link'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Loader2, AlertCircle, Star, Users, Trophy, BookOpen, Zap } from 'lucide-react'
import { Markdown } from '@/components/ui/markdown'
import { motion } from 'framer-motion'
import { dojoService } from '@/services/dojo'
import ninjaImage from '@/assets/ninja.png'
import { HomePageClient } from './home-client'

interface Dojo {
  id: string
  name: string
  description?: string
  official: boolean
  award?: {
    belt?: string
    emoji?: string
  }
  modules: number
  challenges: number
  active_hackers: number
}

async function getDojos(): Promise<Dojo[]> {
  try {
    const response = await dojoService.getDojos()
    return response.dojos || []
  } catch (error) {
    console.error('Failed to fetch dojos:', error)
    // Return mock data for development/when API is unavailable
    return [
      {
        id: 'welcome',
        name: 'Welcome',
        description: 'Welcome to the dojo platform',
        official: true,
        modules: 3,
        challenges: 5,
        active_hackers: 10
      }
    ]
  }
}

export default async function HomePage() {
  const dojos = await getDojos()

  return <HomePageClient dojos={dojos} />
}