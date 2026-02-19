export const dynamic = 'auto'

import Link from 'next/link'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Loader2, AlertCircle, Star, Users, Trophy, BookOpen, Zap } from 'lucide-react'
import { Markdown } from '@/components/ui/markdown'
import { motion } from 'framer-motion'
import { dojoService } from '@/services/dojo'
import ninjaImage from '@/assets/ninja.png'
import { HomePageClient, Dojo } from './home-client'

async function getDojos(): Promise<Dojo[]> {
  try {
    // Use dojoService for server-side fetching (handles SSL properly)
    const response = await dojoService.getDojos()
    return response.dojos || []
  } catch (error) {
    console.error('Failed to fetch dojos:', error)
    // Return empty array when API is unavailable
    return []
  }
}

export default async function HomePage() {
  const dojos = await getDojos()

  return <HomePageClient dojos={dojos} />
}
