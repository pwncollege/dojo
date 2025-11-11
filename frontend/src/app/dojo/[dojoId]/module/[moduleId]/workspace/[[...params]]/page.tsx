import { dojoService } from '@/services/dojo'
import { WorkspacePageClient } from './workspace-client'
import { notFound } from 'next/navigation'

interface WorkspacePageProps {
  params: Promise<{
    dojoId: string
    moduleId: string
    params?: string[]
  }>
}

async function getDojoWithModule(dojoId: string, moduleId: string) {
  try {
    const response = await dojoService.getDojoDetail(dojoId)
    const dojo = response.dojo
    const module = dojo.modules.find(m => m.id === moduleId)
    return { dojo, module }
  } catch (error) {
    console.error('Failed to fetch dojo detail:', error)
    return {
      dojo: {
        id: dojoId,
        name: dojoId.charAt(0).toUpperCase() + dojoId.slice(1),
        description: `This is the ${dojoId} dojo`,
        official: true,
        modules: []
      },
      module: {
        id: moduleId,
        name: 'Module 1',
        description: 'First module',
        challenges: [
          {
            id: 'challenge1',
            name: 'Challenge 1',
            required: true,
            description: 'First challenge'
          }
        ]
      }
    }
  }
}

export default async function WorkspacePage({ params }: WorkspacePageProps) {
  const resolvedParams = await params
  const { dojoId, moduleId, params: urlParams } = resolvedParams

  if (!dojoId || !moduleId) {
    notFound()
  }

  const { dojo, module } = await getDojoWithModule(dojoId, moduleId)

  if (!dojo || !module) {
    notFound()
  }

  return (
    <WorkspacePageClient
      dojo={dojo}
      module={module}
      dojoId={dojoId}
      moduleId={moduleId}
      urlParams={urlParams}
    />
  )
}

