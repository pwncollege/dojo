'use client'

import { useEffect } from 'react'
import { ErrorPage } from '@/components/ui/error-page'

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Application error:', error)
  }, [error])

  return (
    <ErrorPage
      title="Oops! Something went wrong"
      description="An unexpected error occurred while processing your request. Our ninja is on it!"
      statusCode={500}
      showRefresh={true}
      showBack={true}
      showHome={true}
    />
  )
}