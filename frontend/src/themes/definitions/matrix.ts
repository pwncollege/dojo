import type { ThemeDefinition } from '../types'

export const matrixTheme: ThemeDefinition = {
  id: 'matrix',
  name: 'Matrix',
  description: 'Welcome to the real world',
  author: 'The Wachowskis',
  previewColors: {
    primary: '#00ff41',
    secondary: '#008f11',
    accent: '#00c128'
  },
  light: {
    background: '#fafcfa',    // very subtle green tint
    foreground: '#1a4a1a',    // darker forest green
    card: '#f0f8f0',          // subtle green card with more contrast
    cardForeground: '#1a4a1a',
    popover: '#f0f8f0',
    popoverForeground: '#1a4a1a',
    primary: '#00aa22',       // vibrant matrix green
    primaryForeground: '#ffffff',
    secondary: '#e8f5e8',     // light green secondary
    secondaryForeground: '#1a4a1a',
    muted: '#f0f8f0',
    mutedForeground: '#4a6a4a', // medium green for muted text
    accent: '#00dd33',        // bright matrix accent
    accentForeground: '#ffffff',
    destructive: '#cc2200',   // red for errors
    destructiveForeground: '#ffffff',
    success: '#00aa22',       // matrix green
    successForeground: '#ffffff',
    border: 'rgba(0,170,34,.15)',
    input: '#f0f8f0',
    ring: '#00aa22',
    chart1: '#00ff41',        // classic matrix green
    chart2: '#00dd33',        // variations of green
    chart3: '#00bb22',
    chart4: '#009911',
    chart5: '#007700',
    sidebar: '#f0f8f0',
    sidebarForeground: '#1a4a1a',
    sidebarPrimary: '#00aa22',
    sidebarPrimaryForeground: '#ffffff',
    sidebarAccent: '#00dd33',
    sidebarAccentForeground: '#ffffff',
    sidebarBorder: 'rgba(0,170,34,.15)',
    sidebarRing: '#00aa22',
    serviceBg: '#fafcfa'
  },
  dark: {
    background: '#000a00',    // pure dark with tiny green tint
    foreground: '#00ff41',    // classic matrix green
    card: '#0a1a0a',          // dark green-tinted card
    cardForeground: '#00e639', // slightly softer green for card text
    popover: '#0a1a0a',
    popoverForeground: '#00e639',
    primary: '#00ff41',       // classic matrix green
    primaryForeground: '#000a00',
    secondary: '#1a2a1a',     // dark green secondary
    secondaryForeground: '#00cc28',
    muted: '#0a1a0a',
    mutedForeground: '#008f11', // darker green for muted text
    accent: '#39ff72',        // brighter matrix accent
    accentForeground: '#000a00',
    destructive: '#ff3333',   // red for errors
    destructiveForeground: '#000a00',
    success: '#00ff41',       // classic matrix green
    successForeground: '#000a00',
    border: 'rgba(0,255,65,.15)',
    input: '#0a1a0a',
    ring: '#00ff41',
    chart1: '#00ff41',        // matrix green variations
    chart2: '#39ff72',
    chart3: '#00e639',
    chart4: '#00cc28',
    chart5: '#00b322',
    sidebar: '#051005',       // slightly different dark for sidebar
    sidebarForeground: '#00ff41',
    sidebarPrimary: '#00ff41',
    sidebarPrimaryForeground: '#000a00',
    sidebarAccent: '#39ff72',
    sidebarAccentForeground: '#000a00',
    sidebarBorder: 'rgba(0,255,65,.1)',
    sidebarRing: '#00ff41',
    serviceBg: '#000a00'
  }
}