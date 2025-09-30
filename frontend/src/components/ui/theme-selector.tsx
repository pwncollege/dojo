import { Check, ChevronDown, Palette, Sun, Moon, Monitor } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTheme } from '@/components/theme/ThemeProvider'
import { getAllThemes } from '@/themes'
import { useState, useEffect } from 'react'

export function ThemeSelector() {
  const { palette, mode, setPalette, toggleMode } = useTheme()
  const themes = getAllThemes()
  const [isHydrated, setIsHydrated] = useState(false)

  useEffect(() => {
    setIsHydrated(true)
  }, [])

  const getModeIcon = () => {
    switch (mode) {
      case 'light':
        return <Sun className="h-4 w-4" />
      case 'dark':
        return <Moon className="h-4 w-4" />
      case 'system':
        return <Monitor className="h-4 w-4" />
    }
  }

  return (
    <div className="flex items-center gap-2">
      {/* Mode Toggle */}
      <Button
        variant="ghost"
        size="sm"
        onClick={toggleMode}
        className="h-9 w-9 p-0"
      >
        {getModeIcon()}
        <span className="sr-only">Toggle theme mode</span>
      </Button>

      {/* Theme Selector */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="h-9 gap-2">
            <Palette className="h-4 w-4" />
            <span className="hidden sm:inline">
              {isHydrated ? themes.find(t => t.id === palette)?.name : ''}
            </span>
            <ChevronDown className="h-3 w-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          <DropdownMenuLabel>Choose Theme</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {themes.map((theme) => (
            <DropdownMenuItem
              key={theme.id}
              onClick={() => setPalette(theme.id)}
              className="flex items-start gap-3 p-3 cursor-pointer"
            >
              <div className="flex items-center gap-2 flex-1">
                <div className="flex gap-1">
                  <div
                    className="w-3 h-3 rounded-full border border-border"
                    style={{ backgroundColor: theme.previewColors.primary }}
                  />
                  <div
                    className="w-3 h-3 rounded-full border border-border"
                    style={{ backgroundColor: theme.previewColors.secondary }}
                  />
                  <div
                    className="w-3 h-3 rounded-full border border-border"
                    style={{ backgroundColor: theme.previewColors.accent }}
                  />
                </div>
                <div className="flex-1">
                  <div className="font-medium">{theme.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {theme.description}
                  </div>
                  {theme.author && (
                    <div className="text-xs text-muted-foreground/70">
                      by {theme.author}
                    </div>
                  )}
                </div>
              </div>
              {palette === theme.id && (
                <Check className="h-4 w-4 text-primary" />
              )}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}