import { useMemo } from 'react'

interface Command {
  id: string
  label: string
  description?: string
  category: string
  shortcut?: string
  action: () => void | Promise<void>
  condition?: () => boolean
}

interface UseCommandsProps {
  // Workspace state
  activeChallenge?: {
    dojoId: string
    moduleId: string
    challengeId: string
    name: string
  }
  modules?: Array<{
    id: string
    name: string
    challenges: Array<{ id: string, name: string }>
  }>
  activeService: string
  sidebarCollapsed: boolean
  isFullScreen: boolean
  headerHidden: boolean
  workspaceStatus?: { active: boolean }

  // Actions
  setActiveService: (service: string) => void
  setSidebarCollapsed: (collapsed: boolean) => void
  setIsFullScreen: (fullScreen: boolean) => void
  setHeaderHidden: (hidden: boolean) => void
  onChallengeStart: (dojoId: string, moduleId: string, challengeId: string) => void
  onChallengeClose: () => void
}

export function useCommands({
  activeChallenge,
  modules,
  activeService,
  sidebarCollapsed,
  isFullScreen,
  headerHidden,
  workspaceStatus,
  setActiveService,
  setSidebarCollapsed,
  setIsFullScreen,
  setHeaderHidden,
  onChallengeStart,
  onChallengeClose
}: UseCommandsProps): Command[] {
  return useMemo(() => {
    const commands: Command[] = []

    // Workspace Control Commands
    commands.push({
      id: 'workspace.toggle-sidebar',
      label: sidebarCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar',
      description: 'Toggle the challenge list sidebar',
      category: 'Workspace',
      shortcut: 'Ctrl+B',
      action: () => setSidebarCollapsed(!sidebarCollapsed)
    })

    commands.push({
      id: 'workspace.toggle-header',
      label: headerHidden ? 'Show Header' : 'Hide Header',
      description: 'Toggle the workspace header visibility',
      category: 'Workspace',
      shortcut: 'Ctrl+H',
      action: () => setHeaderHidden(!headerHidden),
      condition: () => !!activeChallenge
    })

    commands.push({
      id: 'workspace.fullscreen-toggle',
      label: isFullScreen ? 'Exit Full Screen' : 'Enter Full Screen',
      description: 'Toggle full screen workspace mode',
      category: 'Workspace',
      shortcut: isFullScreen ? 'Esc' : 'F11',
      action: () => setIsFullScreen(!isFullScreen),
      condition: () => !!activeChallenge
    })

    // Service Switching Commands (only when workspace is active)
    if (activeChallenge && workspaceStatus?.active) {
      commands.push({
        id: 'service.terminal',
        label: 'Switch to Terminal',
        description: 'Access the terminal environment',
        category: 'Services',
        shortcut: 'Ctrl+1',
        action: () => setActiveService('terminal')
      })

      commands.push({
        id: 'service.code',
        label: 'Switch to Code Editor',
        description: 'Open VS Code in the workspace',
        category: 'Services',
        shortcut: 'Ctrl+2',
        action: () => setActiveService('code')
      })

      commands.push({
        id: 'service.desktop',
        label: 'Switch to Desktop',
        description: 'Access the desktop environment',
        category: 'Services',
        shortcut: 'Ctrl+3',
        action: () => setActiveService('desktop')
      })
    }

    // Navigation Commands
    if (activeChallenge) {
      commands.push({
        id: 'challenge.close',
        label: 'Close Challenge',
        description: 'Return to the challenge list',
        category: 'Navigation',
        shortcut: 'Ctrl+W',
        action: () => onChallengeClose()
      })

      // Find current challenge index for next/previous
      const currentModule = modules?.find(m => m.id === activeChallenge.moduleId)
      const currentChallengeIndex = currentModule?.challenges.findIndex(c => c.id === activeChallenge.challengeId) ?? -1

      if (currentModule && currentChallengeIndex > 0) {
        const previousChallenge = currentModule.challenges[currentChallengeIndex - 1]
        commands.push({
          id: 'challenge.previous',
          label: 'Previous Challenge',
          description: `Go to ${previousChallenge.name}`,
          category: 'Navigation',
          action: () => onChallengeStart(activeChallenge.dojoId, currentModule.id, previousChallenge.id)
        })
      }

      if (currentModule && currentChallengeIndex < currentModule.challenges.length - 1) {
        const nextChallenge = currentModule.challenges[currentChallengeIndex + 1]
        commands.push({
          id: 'challenge.next',
          label: 'Next Challenge',
          description: `Go to ${nextChallenge.name}`,
          category: 'Navigation',
          action: () => onChallengeStart(activeChallenge.dojoId, currentModule.id, nextChallenge.id)
        })
      }
    }

    // Quick Actions
    if (activeChallenge) {
      commands.push({
        id: 'flag.focus',
        label: 'Focus Flag Input',
        description: 'Focus the flag submission input field',
        category: 'Quick Actions',
        shortcut: 'Ctrl+Shift+F',
        action: () => {
          // Focus flag input in header
          const flagInput = document.querySelector('input[placeholder*="flag"], input[type="text"]') as HTMLInputElement
          if (flagInput) {
            flagInput.focus()
            flagInput.select()
          }
        }
      })
    }

    if (activeChallenge) {
      commands.push({
        id: 'workspace.reset',
        label: 'Reset Workspace',
        description: 'Restart all workspace services',
        category: 'Quick Actions',
        shortcut: 'Ctrl+Shift+R',
        action: () => {
          // TODO: Implement workspace reset when API is available
        }
      })
    }

    // Help
    commands.push({
      id: 'help.shortcuts',
      label: 'Show Keyboard Shortcuts',
      description: 'View all available keyboard shortcuts',
      category: 'Help',
      shortcut: 'Ctrl+/',
      action: () => {
        // TODO: Implement shortcuts help modal
      }
    })

    // Filter commands based on conditions
    return commands.filter(command => !command.condition || command.condition())
  }, [
    activeChallenge,
    modules,
    activeService,
    sidebarCollapsed,
    isFullScreen,
    headerHidden,
    workspaceStatus,
    setActiveService,
    setSidebarCollapsed,
    setIsFullScreen,
    setHeaderHidden,
    onChallengeStart,
    onChallengeClose
  ])
}