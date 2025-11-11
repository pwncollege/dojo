interface ThemeColors {
  // Core colors
  background: string
  foreground: string
  card: string
  cardForeground: string
  popover: string
  popoverForeground: string
  primary: string
  primaryForeground: string
  secondary: string
  secondaryForeground: string
  muted: string
  mutedForeground: string
  accent: string
  accentForeground: string
  destructive: string
  destructiveForeground: string
  border: string
  input: string
  ring: string

  // Chart colors
  chart1: string
  chart2: string
  chart3: string
  chart4: string
  chart5: string

  // Sidebar colors
  sidebar: string
  sidebarForeground: string
  sidebarPrimary: string
  sidebarPrimaryForeground: string
  sidebarAccent: string
  sidebarAccentForeground: string
  sidebarBorder: string
  sidebarRing: string

  // Service container
  serviceBg: string
}

interface ThemeDefinition {
  id: string
  name: string
  description: string
  author?: string
  previewColors: {
    primary: string
    secondary: string
    accent: string
  }
  light: ThemeColors
  dark: ThemeColors
}

type ThemeMode = 'light' | 'dark' | 'system'

export type { ThemeColors, ThemeDefinition, ThemeMode }