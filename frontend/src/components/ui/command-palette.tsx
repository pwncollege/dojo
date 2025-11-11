import { useState, useEffect, useRef, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import {
  Search,
  Command as CommandIcon,
  Keyboard,
  X
} from 'lucide-react'
import { cn } from '@/lib/utils'
interface KeyMap {
  key: string
  ctrlKey?: boolean
  metaKey?: boolean
  shiftKey?: boolean
  altKey?: boolean
}

interface Command {
  id: string
  label: string
  description?: string
  category: string
  shortcut?: string
  action: () => void | Promise<void>
  condition?: () => boolean
  icon?: string
}

function formatKeymap(keymap: KeyMap): string {
  const parts: string[] = []
  if (keymap.ctrlKey) parts.push('Ctrl')
  if (keymap.metaKey) parts.push('Cmd')
  if (keymap.shiftKey) parts.push('Shift')
  if (keymap.altKey) parts.push('Alt')
  if (keymap.key === ' ') {
    parts.push('Space')
  } else if (keymap.key === 'Escape') {
    parts.push('Esc')
  } else if (keymap.key.length === 1) {
    parts.push(keymap.key.toUpperCase())
  } else {
    parts.push(keymap.key)
  }
  return parts.join(' + ')
}

interface CommandPaletteProps {
  isOpen: boolean
  onClose: () => void
  commands: Command[]
}

export function CommandPalette({ isOpen, onClose, commands }: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const filteredCommands = useMemo(() => {
    if (!query.trim()) return commands

    const searchTerm = query.toLowerCase()
    return commands.filter(command =>
      command.label.toLowerCase().includes(searchTerm) ||
      command.description?.toLowerCase().includes(searchTerm) ||
      command.category.toLowerCase().includes(searchTerm)
    ).sort((a, b) => {
      // Prioritize exact matches in label
      const aLabelMatch = a.label.toLowerCase().includes(searchTerm)
      const bLabelMatch = b.label.toLowerCase().includes(searchTerm)
      if (aLabelMatch && !bLabelMatch) return -1
      if (!aLabelMatch && bLabelMatch) return 1
      return 0
    })
  }, [commands, query])

  const groupedCommands = useMemo(() => {
    const groups: Record<string, Command[]> = {}
    filteredCommands.forEach(command => {
      if (!groups[command.category]) {
        groups[command.category] = []
      }
      groups[command.category].push(command)
    })
    return groups
  }, [filteredCommands])

  useEffect(() => {
    if (isOpen) {
      setQuery('')
      setSelectedIndex(0)
      // Focus input after a small delay to ensure portal is rendered
      setTimeout(() => {
        inputRef.current?.focus()
      }, 0)
    }
  }, [isOpen])

  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

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
            prev < filteredCommands.length - 1 ? prev + 1 : 0
          )
          break
        case 'ArrowUp':
          e.preventDefault()
          setSelectedIndex(prev =>
            prev > 0 ? prev - 1 : filteredCommands.length - 1
          )
          break
        case 'Enter':
          e.preventDefault()
          if (filteredCommands[selectedIndex]) {
            filteredCommands[selectedIndex].action()
            onClose()
          }
          break
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, selectedIndex, filteredCommands, onClose])

  if (!isOpen) return null

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-background/80 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Command Palette */}
      <div
        ref={containerRef}
        className="relative w-full max-w-2xl mx-4 bg-background border border-border rounded-lg shadow-2xl animate-in fade-in slide-in-from-top-2 duration-200"
      >
        {/* Search Header */}
        <div className="flex items-center gap-3 p-4 border-b border-border">
          <Search className="h-5 w-5 text-muted-foreground flex-shrink-0" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Type a command or search... (Ctrl+Shift+P)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 bg-transparent text-sm placeholder:text-muted-foreground outline-none"
          />
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs">
              <Keyboard className="h-3 w-3 mr-1" />
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

        {/* Commands List */}
        <ScrollArea className="max-h-96">
          <div className="p-2">
            {Object.keys(groupedCommands).length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">
                <CommandIcon className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p>No commands found</p>
                <p className="text-sm mt-1">Try a different search term</p>
              </div>
            ) : (
              Object.entries(groupedCommands).map(([category, categoryCommands]) => {
                let currentIndex = 0
                for (const cat of Object.keys(groupedCommands)) {
                  if (cat === category) break
                  currentIndex += groupedCommands[cat].length
                }

                return (
                  <div key={category} className="mb-4">
                    <div className="px-3 py-1 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      {category}
                    </div>
                    <div className="space-y-1">
                      {categoryCommands.map((command, index) => {
                        const globalIndex = currentIndex + index
                        const isSelected = globalIndex === selectedIndex

                        return (
                          <div
                            key={command.id}
                            className={cn(
                              "flex items-center justify-between p-3 rounded-md cursor-pointer transition-colors",
                              isSelected
                                ? "bg-primary text-primary-foreground"
                                : "hover:bg-muted"
                            )}
                            onClick={() => {
                              command.action()
                              onClose()
                            }}
                          >
                            <div className="flex-1 min-w-0">
                              <div className="font-medium text-sm">{command.label}</div>
                              {command.description && (
                                <div className={cn(
                                  "text-xs mt-0.5",
                                  isSelected ? "text-primary-foreground/70" : "text-muted-foreground"
                                )}>
                                  {command.description}
                                </div>
                              )}
                            </div>
                            {command.shortcut && (
                              <div className="flex gap-1 ml-4">
                                <Badge
                                  variant={isSelected ? "secondary" : "outline"}
                                  className="text-xs font-mono"
                                >
                                  {command.shortcut}
                                </Badge>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </ScrollArea>

        {/* Footer */}
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
            {filteredCommands.length} command{filteredCommands.length !== 1 ? 's' : ''}
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}