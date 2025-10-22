'use client'

import { useState, useEffect, useRef, useMemo, useCallback, memo } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, BookOpen, Target, Folder, X } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { searchService, type SearchResponse } from '@/services/search'
import { useDebounce } from '@/hooks/useDebounce'

interface SearchModalProps {
  isOpen: boolean
  onClose: () => void
}

interface SearchResultItemProps {
  type: 'dojo' | 'module' | 'challenge'
  name: string
  link: string
  match?: string
  metadata?: {
    dojo?: { name: string }
    module?: { name: string }
  }
  isSelected: boolean
  onClick: () => void
}

const SearchResultItem = memo(function SearchResultItem({ type, name, link, match, metadata, isSelected, onClick }: SearchResultItemProps) {
  const getIcon = () => {
    switch (type) {
      case 'dojo':
        return <BookOpen className="h-4 w-4" />
      case 'module':
        return <Folder className="h-4 w-4" />
      case 'challenge':
        return <Target className="h-4 w-4" />
    }
  }

  const getTypeColor = () => {
    switch (type) {
      case 'dojo':
        return 'text-blue-500'
      case 'module':
        return 'text-green-500'
      case 'challenge':
        return 'text-purple-500'
    }
  }

  return (
    <div
      data-search-item
      className={cn(
        "flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all duration-200 group border border-transparent",
        isSelected
          ? "bg-primary/5 border-primary/20 text-foreground"
          : "hover:bg-muted/50 hover:border-muted-foreground/10"
      )}
      onClick={onClick}
    >
      <div className={cn("flex-shrink-0", getTypeColor())}>
        {getIcon()}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <div className="font-medium text-sm truncate">{name}</div>
          <Badge
            variant={isSelected ? "default" : "outline"}
            className={cn(
              "text-xs capitalize",
              isSelected ? "bg-primary/10 text-primary border-primary/20" : ""
            )}
          >
            {type}
          </Badge>
        </div>

        {metadata && (
          <div className={cn(
            "text-xs",
            isSelected ? "text-muted-foreground/80" : "text-muted-foreground"
          )}>
            {metadata.dojo && (
              <span>{metadata.dojo.name}</span>
            )}
            {metadata.module && metadata.dojo && (
              <span> / {metadata.module.name}</span>
            )}
          </div>
        )}

        {match && (
          <div
            className={cn(
              "text-xs mt-1",
              isSelected ? "text-muted-foreground/80" : "text-muted-foreground"
            )}
            dangerouslySetInnerHTML={{ __html: match }}
          />
        )}
      </div>
    </div>
  )
})

export function SearchModal({ isOpen, onClose }: SearchModalProps) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [results, setResults] = useState<SearchResponse['results']>({
    dojos: [],
    modules: [],
    challenges: []
  })
  const [isLoading, setIsLoading] = useState(false)
  const [mounted, setMounted] = useState(false)

  const inputRef = useRef<HTMLInputElement>(null)
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const selectedItemRef = useRef<HTMLDivElement>(null)
  const router = useRouter()

  const debouncedQuery = useDebounce(query, 300)

  useEffect(() => {
    setMounted(true)
  }, [])

  // Memoized navigation handler
  const handleNavigation = useCallback((link: string) => {
    router.push(link)
    onClose()
  }, [router, onClose])

  // Flatten results for navigation
  const allResults = useMemo(() => {
    const flattened: Array<{
      type: 'dojo' | 'module' | 'challenge'
      name: string
      link: string
      match?: string
      metadata?: { dojo?: { name: string }, module?: { name: string } }
      uniqueKey: string
    }> = []

    results.dojos.forEach(item => {
      flattened.push({
        type: 'dojo',
        ...item,
        uniqueKey: `dojo-${item.id}`
      })
    })

    results.modules.forEach(item => {
      flattened.push({
        type: 'module',
        ...item,
        metadata: { dojo: item.dojo },
        uniqueKey: `module-${item.dojo.id}-${item.id}`
      })
    })

    results.challenges.forEach(item => {
      flattened.push({
        type: 'challenge',
        ...item,
        metadata: { dojo: item.dojo, module: item.module },
        uniqueKey: `challenge-${item.dojo.id}-${item.module.id}-${item.id}`
      })
    })

    return flattened
  }, [results])

  // Search effect
  useEffect(() => {
    if (!debouncedQuery.trim()) {
      setResults({ dojos: [], modules: [], challenges: [] })
      return
    }

    const performSearch = async () => {
      setIsLoading(true)
      try {
        const response = await searchService.search(debouncedQuery)
        if (response.success) {
          setResults(response.results)
        }
      } catch (error) {
        console.error('Search failed:', error)
        setResults({ dojos: [], modules: [], challenges: [] })
      } finally {
        setIsLoading(false)
      }
    }

    performSearch()
  }, [debouncedQuery])

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setQuery('')
      setSelectedIndex(0)
      setResults({ dojos: [], modules: [], challenges: [] })
      setTimeout(() => {
        inputRef.current?.focus()
      }, 0)
    }
  }, [isOpen])

  // Reset selected index when results change
  useEffect(() => {
    setSelectedIndex(0)
  }, [allResults])

  // Scroll selected item into view
  useEffect(() => {
    if (scrollAreaRef.current && selectedIndex >= 0) {
      const container = scrollAreaRef.current.querySelector('[data-radix-scroll-area-viewport]')
      const items = container?.querySelectorAll('[data-search-item]')
      const selectedItem = items?.[selectedIndex] as HTMLElement

      if (selectedItem && container) {
        const containerRect = container.getBoundingClientRect()
        const itemRect = selectedItem.getBoundingClientRect()

        if (itemRect.bottom > containerRect.bottom) {
          selectedItem.scrollIntoView({ block: 'end', behavior: 'smooth' })
        } else if (itemRect.top < containerRect.top) {
          selectedItem.scrollIntoView({ block: 'start', behavior: 'smooth' })
        }
      }
    }
  }, [selectedIndex])

  // Keyboard navigation
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      switch (e.key) {
        case 'Escape':
          e.preventDefault()
          onClose()
          break
        case 'ArrowDown':
          e.preventDefault()
          setSelectedIndex(prev =>
            prev < allResults.length - 1 ? prev + 1 : 0
          )
          break
        case 'ArrowUp':
          e.preventDefault()
          setSelectedIndex(prev =>
            prev > 0 ? prev - 1 : allResults.length - 1
          )
          break
        case 'Enter':
          e.preventDefault()
          if (allResults[selectedIndex]) {
            handleNavigation(allResults[selectedIndex].link)
          }
          break
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, selectedIndex, allResults, handleNavigation, onClose])

  if (!mounted || !isOpen) return null

  return createPortal(
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]"
      >
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 bg-background/80 backdrop-blur-sm"
          onClick={onClose}
        />

        {/* Search Modal */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: -20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: -20 }}
          transition={{ type: "spring", bounce: 0.2, duration: 0.3 }}
          className="relative w-full max-w-2xl mx-4 bg-background border border-border rounded-lg shadow-2xl overflow-hidden"
        >
          {/* Search Header */}
          <div className="flex items-center gap-3 p-4 border-b border-border">
            <Search className="h-5 w-5 text-muted-foreground flex-shrink-0" />
            <input
              ref={inputRef}
              type="text"
              placeholder="Search dojos, modules, and challenges... (Ctrl+K)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1 bg-transparent text-sm placeholder:text-muted-foreground outline-none"
            />
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-xs">
                Esc to close
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0"
                onClick={onClose}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* Results */}
          <ScrollArea ref={scrollAreaRef} className="h-[400px]">
            <div className="p-2">
              {isLoading ? (
                <div className="p-8 text-center text-muted-foreground">
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                    className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full mx-auto mb-2"
                  />
                  <p>Searching...</p>
                </div>
              ) : allResults.length === 0 ? (
                query.trim() ? (
                  <div className="p-8 text-center text-muted-foreground">
                    <Search className="h-8 w-8 mx-auto mb-2 opacity-50" />
                    <p>No results found</p>
                    <p className="text-sm mt-1">Try a different search term</p>
                  </div>
                ) : (
                  <div className="p-8 text-center text-muted-foreground">
                    <Search className="h-8 w-8 mx-auto mb-2 opacity-50" />
                    <p>Start typing to search</p>
                    <p className="text-sm mt-1">Search across dojos, modules, and challenges</p>
                  </div>
                )
              ) : (
                <div className="space-y-1">
                  {allResults.map((result, index) => (
                    <SearchResultItem
                      key={result.uniqueKey}
                      type={result.type}
                      name={result.name}
                      link={result.link}
                      match={result.match}
                      metadata={result.metadata}
                      isSelected={index === selectedIndex}
                      onClick={() => handleNavigation(result.link)}
                    />
                  ))}
                </div>
              )}
            </div>
          </ScrollArea>

          {/* Footer */}
          {allResults.length > 0 && (
            <div className="flex items-center justify-between p-3 border-t border-border text-xs text-muted-foreground">
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-1">
                  <Badge variant="outline" className="text-xs">↑↓</Badge>
                  <span>Navigate</span>
                </div>
                <div className="flex items-center gap-1">
                  <Badge variant="outline" className="text-xs">↵</Badge>
                  <span>Select</span>
                </div>
              </div>
              <div>
                {allResults.length} result{allResults.length !== 1 ? 's' : ''}
              </div>
            </div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body
  )
}