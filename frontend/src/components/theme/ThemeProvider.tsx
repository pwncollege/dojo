import React, { createContext, useContext, useEffect, useState } from 'react'
import { getTheme, getDefaultTheme, themeExists, themeColorsToCSSVars, type ThemeMode } from '@/themes'

interface ThemeContextType {
  palette: string
  mode: ThemeMode
  setPalette: (palette: string) => void
  setMode: (mode: ThemeMode) => void
  toggleMode: () => void
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

export function ThemeProvider({
  children,
  defaultTheme = 'system',
  storageKey = 'dojo-ui-theme'
}: {
  children: React.ReactNode
  defaultTheme?: ThemeMode
  storageKey?: string
}) {
  const [palette, setPalette] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('theme-palette')
      const defaultTheme = getDefaultTheme()
      return (saved && themeExists(saved)) ? saved : defaultTheme.id
    }
    return getDefaultTheme().id
  })

  const [mode, setMode] = useState<ThemeMode>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem(storageKey)
      return (saved as ThemeMode) || defaultTheme
    }
    return defaultTheme
  })

  const toggleMode = () => {
    if (mode === 'system') {
      setMode('light')
    } else if (mode === 'light') {
      setMode('dark')
    } else {
      setMode('system')
    }
  }

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('theme-palette', palette)
    }
  }, [palette])

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem(storageKey, mode)
    }
  }, [mode, storageKey])

  useEffect(() => {
    const root = document.documentElement

    // Clear all existing CSS variables and theme classes
    root.classList.remove('light', 'dark')

    // Get the current theme
    const currentTheme = getTheme(palette)
    if (!currentTheme) {
      console.warn(`Theme "${palette}" not found, falling back to default`)
      setPalette(getDefaultTheme().id)
      return
    }

    // Determine the resolved mode
    let resolvedMode = mode
    if (mode === 'system') {
      resolvedMode = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }

    // Get the appropriate colors for the resolved mode
    const colors = resolvedMode === 'dark' ? currentTheme.dark : currentTheme.light

    // Apply CSS variables
    const cssVars = themeColorsToCSSVars(colors)
    Object.entries(cssVars).forEach(([property, value]) => {
      root.style.setProperty(property, value)
    })

    // Add mode class for any remaining theme-specific styles
    if (resolvedMode === 'dark') {
      root.classList.add('dark')
    }
  }, [palette, mode])

  return (
    <ThemeContext.Provider value={{ palette, mode, setPalette, setMode, toggleMode }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}