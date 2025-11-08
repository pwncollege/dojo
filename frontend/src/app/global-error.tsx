'use client'

import { useEffect } from 'react'
import { ErrorPage } from '@/components/ui/error-page'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Global error:', error)
  }, [error])

  return (
    <html>
      <body>
        <ErrorPage
          title="Critical Error"
          description="A critical error occurred. Please refresh the page or contact support if the problem persists."
          statusCode={500}
          showRefresh={true}
          showBack={false}
          showHome={true}
        />
      </body>
    </html>
  )
}