import { useEffect, useRef } from 'react'

export interface HotkeyConfig {
  key: string
  ctrl?: boolean
  cmd?: boolean
  shift?: boolean
  alt?: boolean
  preventDefault?: boolean
}

export type HotkeyHandler = () => void

// Convert hotkey config to string for mapping
function hotkeyToString(config: HotkeyConfig): string {
  const parts: string[] = []
  if (config.ctrl) parts.push('ctrl')
  if (config.cmd) parts.push('cmd')
  if (config.shift) parts.push('shift')
  if (config.alt) parts.push('alt')
  parts.push(config.key.toLowerCase())
  return parts.join('+')
}

// Check if event matches hotkey config
function matchesHotkey(event: KeyboardEvent, config: HotkeyConfig): boolean {
  const eventKey = event.key.toLowerCase()
  const configKey = config.key.toLowerCase()

  // Handle special keys
  let keyMatches = false
  if (configKey === 'escape' && eventKey === 'escape') keyMatches = true
  else if (configKey === 'enter' && eventKey === 'enter') keyMatches = true
  else if (configKey === 'space' && eventKey === ' ') keyMatches = true
  else if (configKey === 'tab' && eventKey === 'tab') keyMatches = true
  else if (configKey.startsWith('f') && /^f\d+$/.test(configKey) && eventKey === configKey) keyMatches = true
  else keyMatches = eventKey === configKey

  if (!keyMatches) return false

  // Check modifiers
  const ctrlPressed = event.ctrlKey || event.metaKey
  const shiftPressed = event.shiftKey
  const altPressed = event.altKey

  const ctrlRequired = config.ctrl || config.cmd
  const shiftRequired = config.shift || false
  const altRequired = config.alt || false

  return (
    ctrlPressed === ctrlRequired &&
    shiftPressed === shiftRequired &&
    altPressed === altRequired
  )
}

// Global hotkey registry
const globalHotkeys = new Map<string, HotkeyHandler>()
let globalListenerAttached = false

// Handle keydown events from main document or iframes
function handleKeydown(event: KeyboardEvent) {
  // Skip if user is typing in an input
  const target = event.target as HTMLElement
  if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
    return
  }

  // Check all registered hotkeys
  for (const [hotkeyString, handler] of globalHotkeys.entries()) {
    const [modifiers, key] = hotkeyString.split('+').reduce((acc, part) => {
      if (['ctrl', 'cmd', 'shift', 'alt'].includes(part)) {
        acc[0].push(part)
      } else {
        acc[1] = part
      }
      return acc
    }, [[] as string[], ''])

    const config: HotkeyConfig = {
      key,
      ctrl: modifiers.includes('ctrl'),
      cmd: modifiers.includes('cmd'),
      shift: modifiers.includes('shift'),
      alt: modifiers.includes('alt'),
      preventDefault: true
    }

    if (matchesHotkey(event, config)) {
      event.preventDefault()
      event.stopPropagation()
      handler()
      return
    }
  }
}


function attachGlobalListener() {
  if (globalListenerAttached) return

  // Attach to main document with capture to catch events before they reach iframes
  document.addEventListener('keydown', handleKeydown, { capture: true })

  // For cross-origin iframes, also listen at the window level
  // This catches some browser-level hotkeys that still bubble up
  window.addEventListener('keydown', handleKeydown, { capture: true })

  globalListenerAttached = true
}

// Hook for registering hotkeys
export function useHotkeys(hotkeys: Record<string, HotkeyHandler>, deps: any[] = []) {
  const hotkeyRefs = useRef<string[]>([])

  useEffect(() => {
    // Ensure global listener is attached
    attachGlobalListener()

    // Clear previous hotkeys from this component
    hotkeyRefs.current.forEach(hotkeyString => {
      globalHotkeys.delete(hotkeyString)
    })
    hotkeyRefs.current = []

    // Register new hotkeys
    Object.entries(hotkeys).forEach(([hotkeyString, handler]) => {
      globalHotkeys.set(hotkeyString, handler)
      hotkeyRefs.current.push(hotkeyString)
    })

    // Cleanup function
    return () => {
      hotkeyRefs.current.forEach(hotkeyString => {
        globalHotkeys.delete(hotkeyString)
      })
    }
  }, deps)
}

// Helper function to create hotkey strings
export const hotkey = {
  cmd: (key: string) => `cmd+${key}`,
  ctrl: (key: string) => `ctrl+${key}`,
  shift: (key: string) => `shift+${key}`,
  alt: (key: string) => `alt+${key}`,
  ctrlShift: (key: string) => `ctrl+shift+${key}`,
  cmdShift: (key: string) => `cmd+shift+${key}`,
  ctrlAlt: (key: string) => `ctrl+alt+${key}`,
  cmdAlt: (key: string) => `cmd+alt+${key}`,
}