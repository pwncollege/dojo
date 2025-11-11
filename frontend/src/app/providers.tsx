'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useEffect, useState } from 'react'
import { initializeStores } from '@/stores'
import { WorkspaceProvider } from '@/components/providers/WorkspaceProvider'
import { ConditionalHeader } from '@/components/layout/ConditionalHeader'
import { ActiveChallengeProvider } from '@/components/providers/ActiveChallengeProvider'
import { WorkspaceOverlayProvider } from '@/components/providers/WorkspaceOverlayProvider'

const queryClient = new QueryClient()
export function Providers({ children }: { children: React.ReactNode }) {

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
              {/* Global workspace overlay - persists across navigation */}
              <WorkspaceOverlayProvider />
            </ActiveChallengeProvider>
          </WorkspaceProvider>
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  )
}
