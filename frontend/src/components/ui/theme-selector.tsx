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
      {/* Theme Selector */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="h-9 gap-2 hover:bg-primary/10 hover:text-primary">
            <Palette className="h-4 w-4" />
            <span className="hidden sm:inline">
              {isHydrated ? themes.find(t => t.id === palette)?.name : ''}
            </span>
            <ChevronDown className="h-3 w-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-[480px] p-2">
          <DropdownMenuLabel className="px-2 py-2 text-sm font-semibold">Choose Theme</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <div className="grid grid-cols-2 gap-2 p-1">
            {themes.map((theme) => (
              <div
                key={theme.id}
                onClick={() => setPalette(theme.id)}
                className={`
                  relative p-3 rounded-lg cursor-pointer transition-all duration-200
                  border-2
                  ${palette === theme.id
                    ? 'border-primary bg-primary/5 shadow-sm'
                    : 'border-transparent hover:border-primary/30 hover:bg-primary/5'
                  }
                `}
              >
                <div className="space-y-2">
                  {/* Color Preview */}
                  <div className="flex gap-1.5">
                    <div
                      className="w-5 h-5 rounded-md border border-border/50 shadow-sm"
                      style={{ backgroundColor: theme.previewColors.primary }}
                    />
                    <div
                      className="w-5 h-5 rounded-md border border-border/50 shadow-sm"
                      style={{ backgroundColor: theme.previewColors.secondary }}
                    />
                    <div
                      className="w-5 h-5 rounded-md border border-border/50 shadow-sm"
                      style={{ backgroundColor: theme.previewColors.accent }}
                    />
                  </div>

                  {/* Theme Info */}
                  <div>
                    <div className="font-semibold text-sm flex items-center justify-between">
                      <span className="truncate">{theme.name}</span>
                      {palette === theme.id && (
                        <Check className="h-4 w-4 text-primary flex-shrink-0 ml-2" />
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground line-clamp-2 mt-0.5">
                      {theme.description}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}