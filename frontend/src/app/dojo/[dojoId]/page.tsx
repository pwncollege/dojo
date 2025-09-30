import { dojoService } from '@/services/dojo'
import { DojoPageClient } from './dojo-client'
import { notFound } from 'next/navigation'

interface DojoPageProps {
  params: Promise<{
    dojoId: string
  }>
}

async function getDojoDetail(dojoId: string) {
  try {
    const response = await dojoService.getDojoDetail(dojoId)
    return response.dojo
  } catch (error) {
    console.error('Failed to fetch dojo detail:', error)
  }
}

export default async function DojoPage({ params }: DojoPageProps) {
  const resolvedParams = await params
  const { dojoId } = resolvedParams

  if (!dojoId) {
    notFound()
  }

  const dojo = await getDojoDetail(dojoId)

  if (!dojo) {
    notFound()
  }

  return <DojoPageClient dojo={dojo} dojoId={dojoId} />
}
