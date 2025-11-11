import { useEffect, useRef, useState, useCallback } from 'react'

interface ClipboardFlagSubmissionOptions {
  enabled: boolean
  onFlagDetected?: (flag: string) => void
  onFlagSubmit?: (flag: string) => Promise<{ success: boolean; message: string }>
  flagPattern?: RegExp
  shouldProcessFlag?: (flag: string) => boolean
}

const DEFAULT_FLAG_PATTERNS = [
  /^pwn\.college\{[^}]+\}$/,  // exact pwn.college flags only
]

export function useClipboardFlagSubmission({
  enabled = true,
  onFlagDetected,
  onFlagSubmit,
  flagPattern,
  shouldProcessFlag
}: ClipboardFlagSubmissionOptions) {
  const [lastClipboardContent, setLastClipboardContent] = useState<string>('')
  const [isMonitoring, setIsMonitoring] = useState(false)
  const intervalRef = useRef<NodeJS.Timeout>()
  const permissionGranted = useRef(false)
  const lastClipboardContentRef = useRef<string>('')

  // Store callbacks in refs to always have latest version
  const onFlagDetectedRef = useRef(onFlagDetected)
  const onFlagSubmitRef = useRef(onFlagSubmit)
  const shouldProcessFlagRef = useRef(shouldProcessFlag)

  // Update refs when callbacks change
  useEffect(() => {
    onFlagDetectedRef.current = onFlagDetected
  }, [onFlagDetected])

  useEffect(() => {
    onFlagSubmitRef.current = onFlagSubmit
  }, [onFlagSubmit])

  useEffect(() => {
    shouldProcessFlagRef.current = shouldProcessFlag
  }, [shouldProcessFlag])

  // Keep ref in sync with state
  useEffect(() => {
    lastClipboardContentRef.current = lastClipboardContent
  }, [lastClipboardContent])

  const isFlag = (text: string): boolean => {
    // Trim and check length
    const trimmed = text.trim()
    if (trimmed.length > 120) {
      return false
    }

    if (flagPattern) {
      return flagPattern.test(trimmed)
    }

    return DEFAULT_FLAG_PATTERNS.some(pattern => pattern.test(trimmed))
  }

  const checkClipboard = async () => {
    if (!enabled || !permissionGranted.current) {
      return
    }

    try {
      const text = await navigator.clipboard.readText()
      const trimmedText = text.trim()
      const currentLastContent = lastClipboardContentRef.current

      if (trimmedText && trimmedText !== currentLastContent) {
        if (isFlag(trimmedText)) {

          // Check if parent wants to process this flag (use ref for latest function)
          if (shouldProcessFlagRef.current && !shouldProcessFlagRef.current(trimmedText)) {
            setLastClipboardContent(trimmedText)
            return
          }

          // Update both state and ref BEFORE calling onFlagDetected
          setLastClipboardContent(trimmedText)
          lastClipboardContentRef.current = trimmedText

          // Use ref for latest callback
          onFlagDetectedRef.current?.(trimmedText)

          if (onFlagSubmitRef.current) {
            try {
              await onFlagSubmitRef.current(trimmedText)
            } catch (error) {
              console.error('[Clipboard Monitor] Flag submission failed:', error)
            }
          }
        } else {
          // Still update lastClipboardContent for non-flags to prevent repeated checks
          setLastClipboardContent(trimmedText)
          lastClipboardContentRef.current = trimmedText
        }
      }
    } catch (error) {
      // Clipboard access failed - user might have denied permission or switched away
      console.warn('[Clipboard Monitor] Clipboard access failed:', error)
    }
  }

  const startMonitoring = async () => {
    if (!navigator.clipboard) {
      console.warn('[Clipboard Monitor] Clipboard API not supported')
      return false
    }

    try {
      // Request clipboard read permission
      const permission = await navigator.permissions.query({ name: 'clipboard-read' as PermissionName })

      if (permission.state === 'granted' || permission.state === 'prompt') {
        // Try to read clipboard to trigger permission prompt if needed
        const initialRead = await navigator.clipboard.readText()
        const trimmedInitial = initialRead.trim()

        // Set initial clipboard content to prevent immediate false positives
        setLastClipboardContent(trimmedInitial)
        lastClipboardContentRef.current = trimmedInitial
        permissionGranted.current = true

        // Start polling clipboard every 500ms
        intervalRef.current = setInterval(checkClipboard, 500)
        setIsMonitoring(true)
        return true
      } else {
        console.warn('[Clipboard Monitor] Clipboard permission denied:', permission.state)
        return false
      }
    } catch (error) {
      console.error('[Clipboard Monitor] Failed to start clipboard monitoring:', error)
      // Try to start anyway in case permission check failed but clipboard works
      try {
        const fallbackRead = await navigator.clipboard.readText()
        const trimmedFallback = fallbackRead.trim()

        // Set initial clipboard content
        setLastClipboardContent(trimmedFallback)
        lastClipboardContentRef.current = trimmedFallback
        permissionGranted.current = true
        intervalRef.current = setInterval(checkClipboard, 500)
        setIsMonitoring(true)
        return true
      } catch (fallbackError) {
        console.error('[Clipboard Monitor] Fallback also failed:', fallbackError)
        return false
      }
    }
  }

  const stopMonitoring = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = undefined
    }
    setIsMonitoring(false)
    permissionGranted.current = false
  }

  useEffect(() => {
    if (enabled) {
      startMonitoring()
    } else {
      stopMonitoring()
    }

    return stopMonitoring
  }, [enabled])


  // Stop monitoring when component unmounts
  useEffect(() => {
    return stopMonitoring
  }, [])

  // Listen for copy events as an additional trigger
  useEffect(() => {
    if (!enabled) return

    const handleCopy = () => {
      // Small delay to let the clipboard update
      setTimeout(checkClipboard, 100)
    }

    const handleVisibilityChange = () => {
      // Resume monitoring when tab becomes visible
      if (!document.hidden && enabled && !isMonitoring) {
        startMonitoring()
      }
    }

    document.addEventListener('copy', handleCopy)
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      document.removeEventListener('copy', handleCopy)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [enabled, isMonitoring])

  return {
    isMonitoring,
    startMonitoring,
    stopMonitoring,
    lastClipboardContent
  }
}