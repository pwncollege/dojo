import type { Resource } from '@/types/api'

export interface ResourceSection {
  title: string
  resources: Resource[]
}

export function parseResourcesIntoSections(resources: Resource[]): ResourceSection[] {
  const sections: ResourceSection[] = []
  let currentSection: ResourceSection | null = null
  let expectingSectionTitle = false

  for (const resource of resources) {
    if (resource.type === 'header') {
      if (currentSection) {
        sections.push(currentSection)
      }
      currentSection = {
        title: '',
        resources: []
      }
      expectingSectionTitle = true
    } else if (expectingSectionTitle && resource.type === 'markdown' && !resource.expandable) {
      if (currentSection) {
        currentSection.title = resource.name
      }
      expectingSectionTitle = false
    } else if (resource.type === 'lecture' || (resource.type === 'markdown' && resource.expandable)) {
      if (currentSection) {
        currentSection.resources.push(resource)
      } else {
        if (!sections.length) {
          sections.push({
            title: 'Resources',
            resources: []
          })
        }
        sections[sections.length - 1].resources.push(resource)
      }
    }
  }

  if (currentSection) {
    sections.push(currentSection)
  }

  return sections
}