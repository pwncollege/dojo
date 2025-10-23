import type { ThemeDefinition } from './types'
import { defaultTheme } from './definitions/default'
import { amethystTheme } from './definitions/amethyst'
import { everforestTheme } from './definitions/everforest'
import { gruvboxTheme } from './definitions/gruvbox'
import { solarizedTheme } from './definitions/solarized'
import { matrixTheme } from './definitions/matrix'
import { perplexityTheme } from './definitions/perplexity'

// Registry of all available themes
export const themeRegistry: Record<string, ThemeDefinition> = {
  default: defaultTheme,
  amethyst: amethystTheme,
  everforest: everforestTheme,
  gruvbox: gruvboxTheme,
  solarized: solarizedTheme,
  matrix: matrixTheme,
  perplexity: perplexityTheme
}

// Get all available themes as an array
export function getAllThemes(): ThemeDefinition[] {
  return Object.values(themeRegistry)
}

// Get a specific theme by ID
export function getTheme(id: string): ThemeDefinition | undefined {
  return themeRegistry[id]
}

// Get all theme IDs
export function getThemeIds(): string[] {
  return Object.keys(themeRegistry)
}

// Check if a theme exists
export function themeExists(id: string): boolean {
  return id in themeRegistry
}

// Get default theme
export function getDefaultTheme(): ThemeDefinition {
  return defaultTheme
}

// Helper to convert ThemeColors to CSS variables
export function themeColorsToCSSVars(colors: any): Record<string, string> {
  return {
    '--background': colors.background,
    '--foreground': colors.foreground,
    '--card': colors.card,
    '--card-foreground': colors.cardForeground,
    '--popover': colors.popover,
    '--popover-foreground': colors.popoverForeground,
    '--primary': colors.primary,
    '--primary-foreground': colors.primaryForeground,
    '--secondary': colors.secondary,
    '--secondary-foreground': colors.secondaryForeground,
    '--muted': colors.muted,
    '--muted-foreground': colors.mutedForeground,
    '--accent': colors.accent,
    '--accent-foreground': colors.accentForeground,
    '--destructive': colors.destructive,
    '--destructive-foreground': colors.destructiveForeground,
    '--success': colors.success,
    '--success-foreground': colors.successForeground,
    '--border': colors.border,
    '--input': colors.input,
    '--ring': colors.ring,
    '--chart-1': colors.chart1,
    '--chart-2': colors.chart2,
    '--chart-3': colors.chart3,
    '--chart-4': colors.chart4,
    '--chart-5': colors.chart5,
    '--sidebar': colors.sidebar,
    '--sidebar-foreground': colors.sidebarForeground,
    '--sidebar-primary': colors.sidebarPrimary,
    '--sidebar-primary-foreground': colors.sidebarPrimaryForeground,
    '--sidebar-accent': colors.sidebarAccent,
    '--sidebar-accent-foreground': colors.sidebarAccentForeground,
    '--sidebar-border': colors.sidebarBorder,
    '--sidebar-ring': colors.sidebarRing,
    '--service-bg': colors.serviceBg || colors.background
  }
}