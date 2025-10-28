import type { ThemeDefinition } from '../types'

export const gruvboxTheme: ThemeDefinition = {
  id: 'gruvbox',
  name: 'Gruvbox',
  description: 'Warm retro-inspired theme',
  author: 'morhetz',
  previewColors: {
    primary: '#98971a',
    secondary: '#b8bb26',
    accent: '#458588'
  },
  light: {
    background: '#fbf1c7',  // light0
    foreground: '#3c3836',  // dark1
    card: '#f2e5bc',        // light0 soft
    cardForeground: '#3c3836',
    popover: '#f2e5bc',     // light0 soft
    popoverForeground: '#3c3836',
    primary: '#98971a',     // green
    primaryForeground: '#fbf1c7',
    secondary: '#d5c4a1',   // light2
    secondaryForeground: '#3c3836',
    muted: '#ebdbb2',       // light1
    mutedForeground: '#665c54',  // dark3
    accent: '#458588',      // blue
    accentForeground: '#fbf1c7',
    destructive: '#cc241d', // red
    destructiveForeground: '#fbf1c7',
    success: '#98971a',     // green
    successForeground: '#fbf1c7',
    border: '#d5c4a1',      // light2
    input: '#ebdbb2',       // light1
    ring: '#98971a',        // green
    chart1: '#98971a',      // green
    chart2: '#d79921',      // yellow
    chart3: '#689d6a',      // aqua
    chart4: '#b16286',      // purple
    chart5: '#458588',      // blue
    sidebar: '#f2e5bc',     // light0 soft
    sidebarForeground: '#3c3836',
    sidebarPrimary: '#98971a',
    sidebarPrimaryForeground: '#fbf1c7',
    sidebarAccent: '#458588',
    sidebarAccentForeground: '#fbf1c7',
    sidebarBorder: '#bdae93',  // light3
    sidebarRing: '#98971a',
    serviceBg: '#fbf1c7'
  },
  dark: {
    background: '#282828',  // dark0
    foreground: '#ebdbb2',  // light1
    card: '#32302f',        // dark0 soft
    cardForeground: '#ebdbb2',
    popover: '#32302f',     // dark0 soft
    popoverForeground: '#ebdbb2',
    primary: '#b8bb26',     // green
    primaryForeground: '#282828',
    secondary: '#504945',   // dark2
    secondaryForeground: '#ebdbb2',
    muted: '#3c3836',       // dark1
    mutedForeground: '#a89984',  // light4
    accent: '#83a598',      // blue
    accentForeground: '#282828',
    destructive: '#fb4934', // red
    destructiveForeground: '#ebdbb2',
    success: '#b8bb26',     // green
    successForeground: '#282828',
    border: '#504945',      // dark2
    input: '#3c3836',       // dark1
    ring: '#b8bb26',        // green
    chart1: '#b8bb26',      // green
    chart2: '#fabd2f',      // yellow
    chart3: '#8ec07c',      // aqua
    chart4: '#d3869b',      // purple
    chart5: '#83a598',      // blue
    sidebar: '#1d2021',     // dark0 hard
    sidebarForeground: '#ebdbb2',
    sidebarPrimary: '#b8bb26',
    sidebarPrimaryForeground: '#282828',
    sidebarAccent: '#83a598',
    sidebarAccentForeground: '#282828',
    sidebarBorder: '#665c54',  // dark3
    sidebarRing: '#b8bb26',
    serviceBg: '#191B1B'
  }
}