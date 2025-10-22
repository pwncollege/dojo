"use client";

import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Flag, Check, X, Loader2, Send, Clipboard, ChevronRight } from 'lucide-react'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useSubmitChallengeSolution, useStartChallenge } from '@/hooks/useDojo'
import { useDojoStore, useUIStore, useWorkspaceStore } from '@/stores'
import { useClipboardFlagSubmission } from '@/hooks/useClipboardFlagSubmission'
import { workspaceService } from '@/services/workspace'
import { useRouter } from 'next/navigation'

interface SmartFlagInputProps {
  dojoId: string
  moduleId: string
  challengeId: string
  onFlagSubmit?: (flag: string) => Promise<{ success: boolean; message: string }>
}

export function SmartFlagInput({
  dojoId,
  moduleId,
  challengeId,
  onFlagSubmit
}: SmartFlagInputProps) {
  const [value, setValue] = useState('')
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [message, setMessage] = useState('')
  const [clipboardFlag, setClipboardFlag] = useState<string>('')
  const [dismissedFlags, setDismissedFlags] = useState<Set<string>>(new Set())
  const [lastProcessedFlag, setLastProcessedFlag] = useState<string>('')
  const [initialClipboardValue, setInitialClipboardValue] = useState<string>('')
  const [isInitialized, setIsInitialized] = useState(false)
  const [clipboardSubmissionResult, setClipboardSubmissionResult] = useState<'fresh_success' | 'already_solved' | 'error' | null>(null)
  const [isClipboardSubmission, setIsClipboardSubmission] = useState(false)
  const [showUnifiedPopup, setShowUnifiedPopup] = useState(false)
  const [popupState, setPopupState] = useState<'clipboard_detection' | 'submission_result' | 'regular_feedback' | null>(null)
  const [isNextChallengeLoading, setIsNextChallengeLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const timeoutRef = useRef<NodeJS.Timeout>()

  const submitSolution = useSubmitChallengeSolution()
  const isSubmitting = submitSolution.isPending
  const addSolve = useDojoStore(state => state.addSolve)
  const router = useRouter()
  const startChallenge = useStartChallenge()
  const setActiveChallenge = useWorkspaceStore(state => state.setActiveChallenge)

  // Helper function to safely show popup with state
  const showPopupWithState = (state: 'clipboard_detection' | 'submission_result' | 'regular_feedback') => {
    setPopupState(state)
    setShowUnifiedPopup(true)
  }

  // Helper function to safely hide popup
  const hidePopup = () => {
    setShowUnifiedPopup(false)
    setPopupState(null)
    // Clean up status and message when manually hiding
    setStatus('idle')
    setMessage('')
  }

  // Flag pattern validation
  const flagPattern = /^pwn\.college\{[^}]+\}$/
  const isValidFlag = flagPattern.test(value)

  // Animation variants for smooth transitions
  const containerVariants = {
    hidden: {
      opacity: 0,
      scale: 0.95,
      y: -10
    },
    visible: {
      opacity: 1,
      scale: 1,
      y: 0,
      transition: {
        type: "spring",
        stiffness: 300,
        damping: 30,
        mass: 0.8,
        staggerChildren: 0.1
      }
    },
    exit: {
      opacity: 0,
      scale: 0.95,
      y: -10,
      transition: {
        duration: 0.2,
        ease: "easeInOut"
      }
    }
  }

  const itemVariants = {
    hidden: { opacity: 0, x: -20 },
    visible: {
      opacity: 1,
      x: 0,
      transition: {
        type: "spring",
        stiffness: 400,
        damping: 25
      }
    }
  }

  const buttonVariants = {
    hidden: { opacity: 0, scale: 0.8 },
    visible: {
      opacity: 1,
      scale: 1,
      transition: {
        type: "spring",
        stiffness: 500,
        damping: 30,
        delay: 0.2
      }
    }
  }

  // Initialize clipboard baseline on mount
  useEffect(() => {
    const initializeClipboard = async () => {
      try {
        if (navigator.clipboard) {
          const initialValue = await navigator.clipboard.readText()
          setInitialClipboardValue(initialValue.trim())

          // Reset state for fresh session
          setDismissedFlags(new Set())
          setLastProcessedFlag('')
        }
      } catch (error) {
        // Could not read initial clipboard
      } finally {
        setIsInitialized(true)
      }
    }

    initializeClipboard()
  }, [])

  // Simplified clipboard flag processing
  const processClipboardFlag = (flag: string) => {

    // Basic checks
    if (!flag.trim()) {
      return
    }

    if (flag === initialClipboardValue) {
      return
    }

    if (showUnifiedPopup) {
      return
    }

    // Clear any existing timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
    }

    // Set the new flag and show unified popup
    setClipboardFlag(flag)
    setLastProcessedFlag(flag)
    showPopupWithState('clipboard_detection')

    // Auto-hide after 15 seconds
    timeoutRef.current = setTimeout(() => {
      hidePopup()
    }, 15000)
  }

  // Clipboard monitoring - only enabled after initialization
  const { isMonitoring } = useClipboardFlagSubmission({
    enabled: isInitialized,
    onFlagDetected: processClipboardFlag,
    shouldProcessFlag: (flag: string) => {
      // Don't process if already dismissed or same as last processed
      const shouldNotProcess = dismissedFlags.has(flag) || flag === lastProcessedFlag
      return !shouldNotProcess
    }
  })

  const submitFlag = async (flag: string) => {
    if (!flag.trim() || isSubmitting) return

    setStatus('idle')

    try {
      // Use custom onFlagSubmit if provided, otherwise use real API
      if (onFlagSubmit) {
        const result = await onFlagSubmit(flag)
        setStatus(result.success ? 'success' : 'error')
        setMessage(result.message)

        // Add solve to store if successful
        if (result.success) {
          addSolve(dojoId, moduleId, challengeId)
        }

        setValue('')
        // Note: Status and message cleanup is now handled by unified popup
      } else {
        // Use real flag submission API
        const submissionData = {
          dojoId,
          moduleId,
          challengeId,
          submission: { submission: flag.trim() }
        }

        const result = await submitSolution.mutateAsync(submissionData)

        if (result.success) {
          if (result.status === 'authentication_required') {
            setStatus('error')
            setMessage('Authentication required. Please log in.')
          } else if (result.status === 'already_solved') {
            setStatus('success')
            setMessage('Challenge already solved!')
          } else {
            setStatus('success')
            setMessage('Correct flag! Well done!')
            // Add solve to store for immediate UI update
            addSolve(dojoId, moduleId, challengeId)
          }
          setValue('')
          // Note: Status and message cleanup is now handled by unified popup
        } else {
          setStatus('error')
          setMessage('Incorrect flag. Try again!')
          setValue('')
          // Note: Status and message cleanup is now handled by unified popup
        }
      }
    } catch (error: any) {
      setStatus('error')

      let errorMessage = 'Failed to submit flag. Please try again.'
      if (error?.status === 401 || error?.status === 403) {
        errorMessage = 'Authentication required. Please log in.'
      } else if (error?.response?.message) {
        errorMessage = error.response.message
      }

      setMessage(errorMessage)
      setValue('')
      // Note: Status and message cleanup is now handled by unified popup
    }
  }


  // Auto-submit when valid flag pattern is detected
  useEffect(() => {
    if (isValidFlag && value !== '') {
      const timeoutId = setTimeout(() => {
        submitFlag(value)
      }, 500) // Small delay to prevent rapid submissions

      return () => clearTimeout(timeoutId)
    }
  }, [value, isValidFlag])

  // Watch for submission results to show in unified popup
  useEffect(() => {
    if ((status === 'success' || status === 'error') && message) {

      // Determine the type of result based on status and message
      if (status === 'success') {
        if (message === 'Challenge already solved!') {
          setClipboardSubmissionResult('already_solved')
        } else {
          setClipboardSubmissionResult('fresh_success')
        }
      } else if (status === 'error') {
        setClipboardSubmissionResult('error')
      }

      // Show unified popup with result state
      if (isClipboardSubmission && clipboardFlag) {
        // This was a clipboard submission - show result in unified popup
        showPopupWithState('submission_result')
        setIsClipboardSubmission(false)
      } else {
        // Regular submission - show as regular feedback ONLY if we don't have clipboard popup open
        if (popupState !== 'clipboard_detection') {
          showPopupWithState('regular_feedback')
        }
      }

      // Auto-hide result state after different delays based on type
      let hideDelay = 8000 // Default 8 seconds
      if (isClipboardSubmission && clipboardFlag) {
        hideDelay = 10000 // Clipboard submissions stay longer (10 seconds)
      } else {
        hideDelay = status === 'success' ? 8000 : 5000 // Success: 8 seconds, Error: 5 seconds
      }

      const resultTimeout = setTimeout(() => {
        hidePopup()
        setClipboardSubmissionResult(null)
        if (isClipboardSubmission) {
          setClipboardFlag('')
        }
        // Clean up status and message after popup hides
        setStatus('idle')
        setMessage('')
      }, hideDelay)

      return () => clearTimeout(resultTimeout)
    }
  }, [status, message, isClipboardSubmission, clipboardFlag, popupState])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation()

    if (e.key === 'Enter') {
      e.preventDefault()
      submitFlag(value)
    }

    if (e.key === 'Escape') {
      setValue('')
    }
  }

  const handleClipboardSubmit = () => {
    const flagToSubmit = clipboardFlag

    // Clear timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
    }

    setValue(flagToSubmit)
    setLastProcessedFlag(flagToSubmit)

    // Mark this as a clipboard submission
    setIsClipboardSubmission(true)
    submitFlag(flagToSubmit)
  }


  const handleClipboardDismiss = () => {
    const flagToDismiss = clipboardFlag

    // Clear timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
    }

    // Add to dismissed flags to prevent re-showing
    setDismissedFlags(prev => new Set([...prev, flagToDismiss]))
    hidePopup()
    setClipboardFlag('')
    setClipboardSubmissionResult(null)
    // DON'T clear lastProcessedFlag - keep it to track what we've processed
    setLastProcessedFlag(flagToDismiss)
  }

  const handleNextChallenge = async () => {

    try {
      setIsNextChallengeLoading(true)

      const response = await workspaceService.getNextChallenge()

      if (response.success && response.dojo && response.module && response.challenge) {
        const nextUrl = `/dojo/${response.dojo}/module/${response.module}/workspace/challenge/${response.challenge}`

        // Get current active challenge from store
        const currentChallenge = useWorkspaceStore.getState().activeChallenge

        // Check if we're switching to a different module
        if (currentChallenge && currentChallenge.moduleId !== response.module) {
          // Different module - need full navigation to load new module data
          router.push(nextUrl)

          // Hide popup before navigation
          hidePopup()
          setClipboardFlag('')
          setClipboardSubmissionResult(null)
        } else {
          // Same module - can do client-side transition
          setActiveChallenge({
            dojoId: response.dojo,
            moduleId: response.module,
            challengeId: response.challenge,
            challengeName: 'Next Challenge',
            dojoName: '',
            moduleName: '',
            isStarting: true
          })

          // Start the next challenge
          await startChallenge.mutateAsync({
            dojoId: response.dojo,
            moduleId: response.module,
            challengeId: response.challenge
          })

          // Update URL without triggering full navigation
          window.history.replaceState(null, '', nextUrl)

          // Hide popup AFTER navigation starts
          hidePopup()
          setClipboardFlag('')
          setClipboardSubmissionResult(null)
        }
      } else {
        // No next challenge available - hide the popup
        hidePopup()
        setClipboardFlag('')
        setClipboardSubmissionResult(null)
      }
    } catch (error) {
      console.error('Failed to get next challenge:', error)
      // Hide the popup even on error
      hidePopup()
      setClipboardFlag('')
      setClipboardSubmissionResult(null)
    } finally {
      setIsNextChallengeLoading(false)
    }
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [])

  const getStatusIcon = () => {
    if (isSubmitting) {
      return <Loader2 className="h-4 w-4 animate-spin text-primary" />
    }

    switch (status) {
      case 'success':
        return <Check className="h-4 w-4 text-primary" />
      case 'error':
        return <X className="h-4 w-4 text-destructive" />
      default:
        if (isValidFlag) {
          return <Send className="h-4 w-4 text-primary" />
        }
        return null
    }
  }


  return (
    <div className="relative">
      <Popover
        open={showUnifiedPopup && !!popupState}
        onOpenChange={(open) => {
          if (!open) {
            hidePopup()
          }
        }}
      >
        <PopoverTrigger asChild>
          <div className={cn(
            "relative flex items-center rounded-lg border h-9 px-3 gap-2 transition-all duration-200",
            {
              'border-muted-foreground/20 bg-muted/30 hover:bg-muted/50': status === 'idle' && !isValidFlag,
              'border-primary/50 bg-primary/5 hover:bg-primary/10': isValidFlag && status === 'idle',
              'border-primary/50 bg-primary/10': status === 'success',
              'border-destructive/50 bg-destructive/5': status === 'error',
            }
          )}>
            <Flag className={cn(
              "h-4 w-4 flex-shrink-0 transition-colors duration-200",
              {
                'text-muted-foreground': status === 'idle' && !isValidFlag,
                'text-primary': isValidFlag && status === 'idle',
                'text-primary': status === 'success',
                'text-destructive': status === 'error',
              }
            )} />

            <input
              ref={inputRef}
              type="text"
              placeholder="Enter flag..."
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isSubmitting}
              className={cn(
                "flex-1 bg-transparent border-0 outline-none text-sm",
                "placeholder:text-muted-foreground/60",
                "disabled:opacity-50 disabled:cursor-not-allowed",
                {
                  'text-foreground': status === 'idle',
                  'text-primary font-medium': isValidFlag && status === 'idle',
                  'text-primary font-medium': status === 'success',
                  'text-destructive font-medium': status === 'error',
                }
              )}
            />

            {getStatusIcon() && (
              <div className="flex-shrink-0">
                {getStatusIcon()}
              </div>
            )}
          </div>
        </PopoverTrigger>

        <PopoverContent
          side="bottom"
          align="start"
          className={cn(
            "w-auto min-w-80 max-w-md p-0 shadow-lg",
            {
              // Theme colors with opaque background + colored overlay
              'bg-background border relative': popupState === 'clipboard_detection',
              'bg-background border-primary relative before:absolute before:inset-0 before:bg-primary/10 before:pointer-events-none': popupState === 'submission_result' && clipboardSubmissionResult !== 'error',
              'bg-background border-destructive relative before:absolute before:inset-0 before:bg-destructive/10 before:pointer-events-none': popupState === 'submission_result' && clipboardSubmissionResult === 'error',
              'bg-background border-primary relative before:absolute before:inset-0 before:bg-primary/10 before:pointer-events-none': popupState === 'regular_feedback' && status === 'success',
              'bg-background border-destructive relative before:absolute before:inset-0 before:bg-destructive/10 before:pointer-events-none': popupState === 'regular_feedback' && status === 'error',
            }
          )}
          sideOffset={4}
          onInteractOutside={(e) => {
            // Prevent closing when clicking outside
          }}
        >
          <AnimatePresence mode="wait">
            {popupState === 'clipboard_detection' && (
              <motion.div
                key="clipboard-detection"
                variants={containerVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="p-4"
              >
                <motion.div variants={itemVariants} className="flex items-center gap-2 mb-3">
                  <motion.div
                    initial={{ rotate: -10, scale: 0 }}
                    animate={{ rotate: 0, scale: 1 }}
                    transition={{ type: "spring", stiffness: 500, delay: 0.1 }}
                  >
                    <Clipboard className="h-4 w-4 text-accent flex-shrink-0" />
                  </motion.div>
                  <span className="text-sm font-medium text-accent">Flag detected in clipboard</span>
                </motion.div>

                <motion.div variants={itemVariants} className="text-xs text-muted-foreground mb-4 font-mono bg-muted/80 p-3 rounded border break-all min-w-0">
                  {clipboardFlag}
                </motion.div>

                <motion.div variants={itemVariants} className="flex flex-wrap gap-2">
                  <motion.div variants={buttonVariants}>
                    <Button
                      size="sm"
                      onClick={handleClipboardSubmit}
                      disabled={isSubmitting}
                    >
                      Submit Flag
                    </Button>
                  </motion.div>
                  <motion.div variants={buttonVariants}>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={handleClipboardDismiss}
                    >
                      Dismiss
                    </Button>
                  </motion.div>
                </motion.div>
              </motion.div>
            )}

            {popupState === 'submission_result' && (
              <motion.div
                key="submission-result"
                variants={containerVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="p-4"
              >
                <motion.div variants={itemVariants} className="flex items-center gap-2 mb-3">
                  <motion.div
                    initial={{ scale: 0, rotate: clipboardSubmissionResult === 'error' ? -90 : 0 }}
                    animate={{ scale: 1, rotate: 0 }}
                    transition={{
                      type: "spring",
                      stiffness: 600,
                      delay: 0.1,
                      duration: 0.6
                    }}
                  >
                    {clipboardSubmissionResult === 'error' ? (
                      <X className="h-4 w-4 text-destructive flex-shrink-0" />
                    ) : (
                      <Check className="h-4 w-4 text-primary flex-shrink-0" />
                    )}
                  </motion.div>
                  <motion.span
                    variants={itemVariants}
                    className="text-sm font-medium"
                  >
                    {clipboardSubmissionResult === 'error'
                      ? 'Incorrect Flag'
                      : clipboardSubmissionResult === 'already_solved'
                        ? 'Already Solved'
                        : 'Congratulations!'
                    }
                  </motion.span>
                </motion.div>

                <motion.div
                  variants={itemVariants}
                  className="text-xs mb-4 opacity-80"
                >
                  {clipboardSubmissionResult === 'error'
                    ? message || 'The flag you submitted is incorrect. Please try again.'
                    : clipboardSubmissionResult === 'already_solved'
                      ? 'This challenge has already been completed.'
                      : 'Flag submitted successfully! Well done solving this challenge.'
                  }
                </motion.div>

                <motion.div variants={itemVariants} className="flex flex-wrap gap-2">
                  {clipboardSubmissionResult === 'fresh_success' && (
                    <motion.div variants={buttonVariants}>
                      <Button
                        size="sm"
                        onClick={handleNextChallenge}
                        disabled={isNextChallengeLoading}
                      >
                        {isNextChallengeLoading ? (
                          <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                        ) : (
                          <ChevronRight className="h-3 w-3 mr-1" />
                        )}
                        {isNextChallengeLoading ? 'Starting...' : 'Next Challenge'}
                      </Button>
                    </motion.div>
                  )}
                  <motion.div variants={buttonVariants}>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={handleClipboardDismiss}
                    >
                      Dismiss
                    </Button>
                  </motion.div>
                </motion.div>
              </motion.div>
            )}

            {popupState === 'regular_feedback' && (
              <motion.div
                key="regular-feedback"
                variants={containerVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="p-4"
              >
                <motion.div variants={itemVariants} className="flex items-center gap-2 mb-2">
                  <motion.div
                    initial={{ scale: 0, rotate: status === 'error' ? -90 : 0 }}
                    animate={{ scale: 1, rotate: 0 }}
                    transition={{
                      type: "spring",
                      stiffness: 600,
                      delay: 0.1,
                      duration: 0.6
                    }}
                  >
                    {status === 'success' ? (
                      <Check className="h-4 w-4 text-primary flex-shrink-0" />
                    ) : (
                      <X className="h-4 w-4 text-destructive flex-shrink-0" />
                    )}
                  </motion.div>
                  <motion.span
                    variants={itemVariants}
                    className="text-sm font-medium"
                  >
                    {status === 'success' ? 'Success!' : 'Error'}
                  </motion.span>
                </motion.div>

                <motion.div
                  variants={itemVariants}
                  className="text-xs mb-4 opacity-80"
                >
                  {message}
                </motion.div>

                <motion.div variants={itemVariants} className="flex flex-wrap gap-2">
                  {status === 'success' && (
                    <motion.div variants={buttonVariants}>
                      <Button
                        size="sm"
                        onClick={handleNextChallenge}
                        disabled={isNextChallengeLoading}
                      >
                        {isNextChallengeLoading ? (
                          <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                        ) : (
                          <ChevronRight className="h-3 w-3 mr-1" />
                        )}
                        {isNextChallengeLoading ? 'Starting...' : 'Next Challenge'}
                      </Button>
                    </motion.div>
                  )}
                  <motion.div variants={buttonVariants}>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={hidePopup}
                      className={status === 'error' ? 'text-destructive hover:text-destructive hover:bg-destructive/10 focus-visible:ring-destructive' : ''}
                    >
                      Dismiss
                    </Button>
                  </motion.div>
                </motion.div>
              </motion.div>
            )}

            {/* Fallback content if no state matches */}
            {!popupState && (
              <motion.div
                key="no-content"
                variants={containerVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="p-4 text-sm text-muted-foreground"
              >
                No content to display
              </motion.div>
            )}
          </AnimatePresence>
        </PopoverContent>
      </Popover>
    </div>
  )
}
