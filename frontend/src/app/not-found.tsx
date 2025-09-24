import { ErrorPage } from '@/components/ui/error-page'

export default function NotFound() {
  return (
    <ErrorPage
      title="Something broke"
      description="The requested page could not be found. Please try again later."
      statusCode={404}
      showRefresh={false}
      showBack={false}
      showHome={false}
    />
  )
}
