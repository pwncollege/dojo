import { redirect } from 'next/navigation'
import { ProfileClient } from './profile-client'

// Mock data for now - replace with actual API calls
async function getUserProfile() {
  // Generate mock activity data for the heatmap
  const activityData = []
  const today = new Date()

  // Generate random activity for past 365 days
  for (let i = 364; i >= 0; i--) {
    const date = new Date(today)
    date.setDate(date.getDate() - i)
    const dateString = date.toISOString().split('T')[0]

    // Random solve count (weighted towards fewer solves, some empty days)
    const random = Math.random()
    let count = 0
    if (random > 0.3) { // 70% chance of having activity
      if (random > 0.85) count = Math.floor(Math.random() * 15) + 10 // 15% high activity
      else if (random > 0.6) count = Math.floor(Math.random() * 5) + 5 // 25% medium
      else count = Math.floor(Math.random() * 3) + 1 // 30% low
    }

    activityData.push({ date: dateString, count })
  }

  // This would be replaced with actual API call
  return {
    user: {
      username: 'hacker',
      email: 'hacker@pwn.college'
    },
    stats: {
      belt: 'yellow',
      beltProgress: 65,
      rank: 42
    },
    recentActivity: [],
    dojoProgress: [],
    activityData
  }
}

export default async function ProfilePage() {
  const data = await getUserProfile()

  if (!data.user) {
    redirect('/login')
  }

  return (
    <ProfileClient
      user={data.user}
      stats={data.stats}
      recentActivity={data.recentActivity}
      dojoProgress={data.dojoProgress}
      activityData={data.activityData}
    />
  )
}
