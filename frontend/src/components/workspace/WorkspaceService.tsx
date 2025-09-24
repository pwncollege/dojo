import { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'

interface WorkspaceServiceProps {
  iframeSrc: string
  activeService: string
  onReady?: () => void
}

export function WorkspaceService({ iframeSrc, activeService, onReady }: WorkspaceServiceProps) {
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isReady, setIsReady] = useState(false)
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const checkIntervalRef = useRef<NodeJS.Timeout | undefined>()
  const retryCount = useRef(0)

  const maxRetries = 30 // 30 seconds
  const checkInterval = 1000 // Check every second

  useEffect(() => {
    // Construct full URL
    const baseUrl = process.env.NEXT_PUBLIC_DOJO_BASE_URL
    const fullUrl = iframeSrc.startsWith('/') ? `${baseUrl}${iframeSrc}` : iframeSrc

    // Check if iframe already has the correct URL - if so, don't reload
    if (iframeRef.current && iframeRef.current.src === fullUrl && isReady) {
      console.log(`${activeService} iframe already loaded with correct URL, skipping reload`)
      return
    }

    setIsLoading(true)
    setError(null)
    setIsReady(false)
    retryCount.current = 0

    // Check if service is actually ready by making a HEAD request
    const checkServiceReady = async () => {
      retryCount.current++

      if (retryCount.current >= maxRetries) {
        setError(`${activeService} service timed out after ${maxRetries} seconds`)
        setIsLoading(false)
        if (checkIntervalRef.current) {
          clearInterval(checkIntervalRef.current)
        }
        return
      }

      try {
        // Make a HEAD request to check if service is ready
        const response = await fetch(fullUrl, {
          method: 'HEAD',
          credentials: 'include', // Include cookies for authentication
        })

        if (response.ok) {
          console.log(`${activeService} service ready (status: ${response.status})`)

          // Service is ready, load it in iframe
          if (iframeRef.current) {
            iframeRef.current.src = fullUrl
          }

          setIsLoading(false)
          // Add small delay to ensure iframe content is rendered before hiding spinner
          setTimeout(() => {
            setIsReady(true)
            setError(null)
            onReady?.()
          }, 100)

          if (checkIntervalRef.current) {
            clearInterval(checkIntervalRef.current)
          }
        } else if (response.status === 502 || response.status === 503) {
          // Service not ready yet, keep checking
          console.log(`${activeService} service not ready yet (${retryCount.current}/${maxRetries})`)
        } else {
          // Unexpected error
          console.error(`${activeService} service returned unexpected status: ${response.status}`)
        }
      } catch (err) {
        // Network error or CORS issue - try loading iframe anyway after a few attempts
        if (retryCount.current > 3) {
          console.log(`${activeService} service check failed, loading anyway (CORS/network issue)`)

          if (iframeRef.current) {
            iframeRef.current.src = fullUrl
          }

          setIsLoading(false)
          // Add small delay to ensure iframe content is rendered before hiding spinner
          setTimeout(() => {
            setIsReady(true)
            setError(null)
            onReady?.()
          }, 100)

          if (checkIntervalRef.current) {
            clearInterval(checkIntervalRef.current)
          }
        } else {
          console.log(`Checking ${activeService} service... (${retryCount.current}/${maxRetries})`)
        }
      }
    }

    // Start checking immediately
    checkServiceReady()
    checkIntervalRef.current = setInterval(checkServiceReady, checkInterval)

    return () => {
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current)
      }
    }
  }, [iframeSrc, activeService, onReady])

  return (
    <div
      className="relative w-full h-full"
      style={{ backgroundColor: activeService === 'terminal' ? 'var(--service-bg)' : 'var(--background)' }}
    >
      {/* Always show iframe, but hide it when not ready */}
      <iframe
        ref={iframeRef}
        className={`w-full h-full border-0 transition-opacity duration-300 ${
          activeService === 'code' ? '' : 'rounded-lg'
        } ${isReady ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
        style={{ backgroundColor: activeService === 'terminal' ? 'var(--service-bg)' : 'var(--background)' }}
        title={`Workspace ${activeService}`}
        allow="clipboard-write"
      />

      {/* Loading overlay when not ready */}
      {!isReady && (
        <motion.div
          className="absolute inset-0 flex items-center justify-center"
          style={{ backgroundColor: activeService === 'terminal' ? 'var(--service-bg)' : 'var(--background)' }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="text-center">
            {isLoading ? (
              <>
                <div className="w-16 h-16 border-4 border-muted border-t-primary rounded-full animate-spin mx-auto mb-4" />
                <p className="text-lg font-medium">Loading {activeService}...</p>
                <p className="text-sm text-muted-foreground mt-2">
                  {activeService === 'code' && 'Starting VS Code environment'}
                  {activeService === 'terminal' && 'Initializing terminal session'}
                  {activeService === 'desktop' && 'Setting up desktop environment'}
                </p>
              </>
            ) : error ? (
              <>
                <div className="w-16 h-16 bg-destructive/10 rounded-full flex items-center justify-center mx-auto mb-4">
                  <span className="text-destructive text-2xl">⚠</span>
                </div>
                <p className="text-lg font-medium text-destructive">Failed to load {activeService}</p>
                <p className="text-sm text-muted-foreground mt-2">{error}</p>
              </>
            ) : null}
          </div>
        </motion.div>
      )}
    </div>
  )
}
