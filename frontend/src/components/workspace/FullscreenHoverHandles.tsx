import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronRight, PanelTop, PanelLeft } from 'lucide-react'

interface FullscreenHoverHandlesProps {
  children: {
    header: React.ReactNode
    sidebar: React.ReactNode
  }
}

export function FullscreenHoverHandles({ children }: FullscreenHoverHandlesProps) {
  const [showHeader, setShowHeader] = useState(false)
  const [showSidebar, setShowSidebar] = useState(false)
  const [headerHovered, setHeaderHovered] = useState(false)
  const [sidebarHovered, setSidebarHovered] = useState(false)
  const headerTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const sidebarTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  // Helper function to check if any dropdown/popover is open
  const isDropdownOpen = () => {
    // Check for common dropdown/popover selectors that indicate UI elements are open
    const selectors = [
      '[data-state="open"]', // Radix UI dropdowns/popovers
      '[data-radix-popper-content-wrapper]', // Radix popper content
      '[role="menu"]', // ARIA menu
      '[role="dialog"]', // Modal dialogs
    ]

    // Only check DOM selectors, remove mouseOverDropdown to avoid interference
    return selectors.some(selector => document.querySelector(selector))
  }


  // Improved auto-hide logic with dropdown detection
  useEffect(() => {
    if (showHeader && !headerHovered) {
      if (headerTimeoutRef.current) {
        clearTimeout(headerTimeoutRef.current)
      }

      headerTimeoutRef.current = setTimeout(() => {
        // Don't hide if a dropdown/popover is open
        if (!isDropdownOpen()) {
          setShowHeader(false)
        } else {
          // Check again shortly if dropdown is still open
          headerTimeoutRef.current = setTimeout(() => {
            if (!isDropdownOpen()) {
              setShowHeader(false)
            }
          }, 300)
        }
      }, 400) // Balanced timeout

      return () => {
        if (headerTimeoutRef.current) {
          clearTimeout(headerTimeoutRef.current)
        }
      }
    }
  }, [showHeader, headerHovered])

  useEffect(() => {
    if (showSidebar && !sidebarHovered) {
      if (sidebarTimeoutRef.current) {
        clearTimeout(sidebarTimeoutRef.current)
      }

      sidebarTimeoutRef.current = setTimeout(() => {
        // Don't hide if a dropdown/popover is open
        if (!isDropdownOpen()) {
          setShowSidebar(false)
        } else {
          // Check again shortly if dropdown is still open
          sidebarTimeoutRef.current = setTimeout(() => {
            if (!isDropdownOpen()) {
              setShowSidebar(false)
            }
          }, 300)
        }
      }, 400) // Balanced timeout

      return () => {
        if (sidebarTimeoutRef.current) {
          clearTimeout(sidebarTimeoutRef.current)
        }
      }
    }
  }, [showSidebar, sidebarHovered])

  return (
    <>
      {/* Top Handle - visible when header is hidden */}
      {!showHeader && (
        <motion.div
          className="fixed top-0 left-1/2 -translate-x-1/2 z-[200]"
          onMouseEnter={() => setShowHeader(true)}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1, duration: 0.3 }}
        >
          <motion.div
            className="bg-primary/20 backdrop-blur-sm rounded-b-lg px-3 py-1 border border-primary/20"
            initial={{ opacity: 0.5, y: -8 }}
            animate={{
              opacity: [0.5, 1, 0.5],
              y: 0
            }}
            transition={{
              opacity: { repeat: Infinity, duration: 2 },
              y: { duration: 0.2 }
            }}
          >
            <PanelTop className="h-3 w-3 text-primary/70" />
          </motion.div>
        </motion.div>
      )}

      {/* Top Edge Trigger Area - invisible wider area */}
      {!showHeader && (
        <div
          className="fixed top-0 left-0 right-0 h-2 z-[199]"
          onMouseEnter={() => setShowHeader(true)}
        />
      )}

      {/* Header + Handle - slides down together */}
      <motion.div
        className="fixed left-0 right-0 z-[200] w-full"
        initial={{ y: -200 }}
        animate={{ y: showHeader ? 0 : -200 }}
        transition={{
          type: "spring",
          stiffness: 400,
          damping: 30
        }}
      >
        {/* Header Panel - minimal wrapper to preserve original styling */}
        <div
          className="shadow-2xl overflow-visible" // Changed to overflow-visible for dropdowns
          onMouseEnter={() => setHeaderHovered(true)}
          onMouseLeave={(e) => {
            // More sophisticated mouse leave detection
            const rect = e.currentTarget.getBoundingClientRect()
            const buffer = 50 // 50px buffer for mouse tolerance
            const { clientX, clientY } = e

            // Only set hovered to false if mouse is truly outside with buffer
            if (
              clientY < rect.top - buffer ||
              clientY > rect.bottom + buffer ||
              clientX < rect.left - buffer ||
              clientX > rect.right + buffer
            ) {
              setHeaderHovered(false)
            }
          }}
        >
          {children.header}
        </div>

        {/* Handle - attached to bottom of header */}
        <div className="flex justify-center">
          <div
            className="bg-primary/20 backdrop-blur-sm rounded-b-lg px-3 py-1 border border-primary/20 border-t-0"
            onMouseEnter={() => {
              setShowHeader(true)
              setHeaderHovered(true)
            }}
            onMouseLeave={() => setHeaderHovered(false)}
          >
            <PanelTop className="h-3 w-3 text-primary/70" />
          </div>
        </div>
      </motion.div>

      {/* Left Handle - visible when sidebar is hidden */}
      {!showSidebar && (
        <motion.div
          className="fixed left-0 top-1/2 -translate-y-1/2 z-[200]"
          onMouseEnter={() => setShowSidebar(true)}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1, duration: 0.3 }}
        >
          <motion.div
            className="bg-primary/20 backdrop-blur-sm rounded-r-lg px-1 py-3 border border-primary/20"
            initial={{ opacity: 0.5, x: -8 }}
            animate={{
              opacity: [0.5, 1, 0.5],
              x: 0
            }}
            transition={{
              opacity: { repeat: Infinity, duration: 2 },
              x: { duration: 0.2 }
            }}
          >
            <PanelLeft className="h-3 w-3 text-primary/70" />
          </motion.div>
        </motion.div>
      )}

      {/* Left Edge Trigger Area - invisible wider area */}
      {!showSidebar && (
        <div
          className="fixed left-0 top-0 bottom-0 w-2 z-[199]"
          onMouseEnter={() => setShowSidebar(true)}
        />
      )}

      {/* Sidebar + Handle - slides from left together */}
      <motion.div
        className="fixed top-0 bottom-0 z-[200]"
        initial={{ x: -420 }}
        animate={{ x: showSidebar ? 0 : -420 }}
        transition={{
          type: "spring",
          stiffness: 400,
          damping: 30
        }}
      >
        <div className="flex h-full">
          {/* Sidebar Panel */}
          <div
            className="w-[380px] shadow-2xl overflow-visible border-r border-border" // Changed to overflow-visible
            onMouseEnter={() => setSidebarHovered(true)}
            onMouseLeave={(e) => {
              // More sophisticated mouse leave detection
              const rect = e.currentTarget.getBoundingClientRect()
              const buffer = 50 // 50px buffer for mouse tolerance
              const { clientX, clientY } = e

              // Only set hovered to false if mouse is truly outside with buffer
              if (
                clientX < rect.left - buffer ||
                clientX > rect.right + buffer ||
                clientY < rect.top - buffer ||
                clientY > rect.bottom + buffer
              ) {
                setSidebarHovered(false)
              }
            }}
          >
            {children.sidebar}
          </div>

          {/* Handle - attached to right of sidebar */}
          <div className="flex items-center">
            <div
              className="bg-primary/20 backdrop-blur-sm rounded-r-lg px-1 py-3 border border-primary/20 border-l-0"
              onMouseEnter={() => {
                setShowSidebar(true)
                setSidebarHovered(true)
              }}
              onMouseLeave={() => setSidebarHovered(false)}
            >
              <PanelLeft className="h-3 w-3 text-primary/70" />
            </div>
          </div>
        </div>
      </motion.div>

    </>
  )
}