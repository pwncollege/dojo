import { useState, useEffect, useRef } from 'react'

interface UseWorkspaceReadinessProps {
  iframeSrc?: string
  enabled?: boolean
}

interface WorkspaceReadinessState {
  isReady: boolean
  isChecking: boolean
  error?: string
}

export function useWorkspaceReadiness({
  iframeSrc,
  enabled = true
}: UseWorkspaceReadinessProps): WorkspaceReadinessState {
  const [state, setState] = useState<WorkspaceReadinessState>({
    isReady: false,
    isChecking: false
  })
  const timeoutRef = useRef<NodeJS.Timeout>()
  const retryTimeoutRef = useRef<NodeJS.Timeout>()

  useEffect(() => {
    if (!enabled || !iframeSrc) {
      setState({ isReady: false, isChecking: false })
      return
    }

    setState({ isReady: false, isChecking: true, error: undefined })

    const checkReadiness = async () => {
      try {
        // Create a hidden iframe to test if the URL loads
        const testIframe = document.createElement('iframe')
        testIframe.style.display = 'none'
        testIframe.style.position = 'absolute'
        testIframe.style.left = '-9999px'

        const url = iframeSrc.startsWith('/')
          ? `http://localhost${iframeSrc}`
          : iframeSrc

        let isResolved = false

        // Set up load handler
        const handleLoad = () => {
          if (!isResolved) {
            isResolved = true
            setState({ isReady: true, isChecking: false })
            document.body.removeChild(testIframe)
            if (timeoutRef.current) clearTimeout(timeoutRef.current)
          }
        }

        // Set up error handler
        const handleError = () => {
          if (!isResolved) {
            isResolved = true
            document.body.removeChild(testIframe)
            if (timeoutRef.current) clearTimeout(timeoutRef.current)

            // Retry after 2 seconds
            retryTimeoutRef.current = setTimeout(checkReadiness, 2000)
          }
        }

        testIframe.onload = handleLoad
        testIframe.onerror = handleError

        // Timeout after 5 seconds and retry
        timeoutRef.current = setTimeout(() => {
          if (!isResolved) {
            isResolved = true
            document.body.removeChild(testIframe)
            retryTimeoutRef.current = setTimeout(checkReadiness, 2000)
          }
        }, 5000)

        // Append to DOM and set src to start loading
        document.body.appendChild(testIframe)
        testIframe.src = url

      } catch (error) {
        retryTimeoutRef.current = setTimeout(checkReadiness, 2000)
      }
    }

    // Start checking
    checkReadiness()

    // Cleanup function
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      if (retryTimeoutRef.current) clearTimeout(retryTimeoutRef.current)
      setState({ isReady: false, isChecking: false })
    }
  }, [iframeSrc, enabled])

  return state
}