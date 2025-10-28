'use client'

import { Users } from 'lucide-react'

export default function Community() {
  return (
    <div className="min-h-screen bg-background text-foreground p-6">
      <div className="max-w-7xl mx-auto text-center py-16">
        <Users className="h-16 w-16 text-muted-foreground mx-auto mb-4" />
        <h1 className="text-2xl font-bold mb-2">Community</h1>
        <p className="text-muted-foreground mb-4">This page is under development</p>
      </div>
    </div>
  )
}