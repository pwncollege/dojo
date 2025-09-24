'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useEffect, useState } from 'react'
import { initializeStores } from '@/stores'
import { WorkspaceProvider } from '@/components/providers/WorkspaceProvider'
import { ConditionalHeader } from '@/components/layout/ConditionalHeader'
import { ActiveChallengeProvider } from '@/components/providers/ActiveChallengeProvider'

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient())

  useEffect(() => {
    initializeStores()
  }, [])

  return (
    <ThemeProvider defaultTheme="system" storageKey="dojo-ui-theme">
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <WorkspaceProvider>
            <ActiveChallengeProvider>
              <ConditionalHeader />
              <main className="flex-1">{children}</main>
            </ActiveChallengeProvider>
          </WorkspaceProvider>
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  )
}