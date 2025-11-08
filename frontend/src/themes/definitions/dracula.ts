import type { ThemeDefinition } from '../types'

export const draculaTheme: ThemeDefinition = {
  id: 'dracula',
  name: 'Dracula',
  description: 'A dark theme for vampires',
  author: 'Dracula Theme',
  previewColors: {
    primary: '#bd93f9',
    secondary: '#ff79c6',
    accent: '#8be9fd'
  },
  light: {
    background: '#f8f8f2',    // light background
    foreground: '#282a36',    // dark text for light mode
    card: '#f1f1ec',          // slightly darker light
    cardForeground: '#282a36',
    popover: '#f1f1ec',
    popoverForeground: '#282a36',
    primary: '#6272a4',       // purple but darker for light mode
    primaryForeground: '#f8f8f2',
    secondary: '#e6e6e6',     // light gray
    secondaryForeground: '#282a36',
    muted: '#f1f1ec',
    mutedForeground: '#6272a4',
    accent: '#50fa7b',        // green
    accentForeground: '#282a36',
    destructive: '#ff5555',   // red
    destructiveForeground: '#f8f8f2',
    border: 'rgba(0,0,0,.1)',
    input: '#f1f1ec',
    ring: '#6272a4',
    chart1: '#50fa7b',        // green
    chart2: '#f1fa8c',        // yellow
    chart3: '#8be9fd',        // cyan
    chart4: '#bd93f9',        // purple
    chart5: '#ff79c6',        // pink
    sidebar: '#f1f1ec',
    sidebarForeground: '#282a36',
    sidebarPrimary: '#6272a4',
    sidebarPrimaryForeground: '#f8f8f2',
    sidebarAccent: '#50fa7b',
    sidebarAccentForeground: '#282a36',
    sidebarBorder: 'rgba(0,0,0,.1)',
    sidebarRing: '#6272a4',
    serviceBg: '#f8f8f2'
  },
  dark: {
    background: '#282a36',    // dracula background
    foreground: '#f8f8f2',    // dracula foreground
    card: '#44475a',          // dracula current line
    cardForeground: 'rgba(255,255,255,.6)',
    popover: '#44475a',
    popoverForeground: '#f8f8f2',
    primary: '#bd93f9',       // dracula purple
    primaryForeground: '#282a36',
    secondary: '#6272a4',     // dracula comment
    secondaryForeground: '#f8f8f2',
    muted: '#44475a',         // dracula current line
    mutedForeground: '#6272a4', // dracula comment
    accent: '#8be9fd',        // dracula cyan
    accentForeground: '#282a36',
    destructive: '#ff5555',   // dracula red
    destructiveForeground: '#f8f8f2',
    border: 'rgba(255,255,255,.1)',
    input: '#44475a',
    ring: '#bd93f9',
    chart1: '#50fa7b',        // dracula green
    chart2: '#f1fa8c',        // dracula yellow
    chart3: '#8be9fd',        // dracula cyan
    chart4: '#bd93f9',        // dracula purple
    chart5: '#ff79c6',        // dracula pink
    sidebar: '#21222c',       // darker than background
    sidebarForeground: '#f8f8f2',
    sidebarPrimary: '#bd93f9',
    sidebarPrimaryForeground: '#282a36',
    sidebarAccent: '#8be9fd',
    sidebarAccentForeground: '#282a36',
    sidebarBorder: 'rgba(255,255,255,.1)',
    sidebarRing: '#bd93f9',
    serviceBg: '#282a36'
  }
}
