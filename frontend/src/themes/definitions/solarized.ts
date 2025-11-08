import type { ThemeDefinition } from '../types'

export const solarizedTheme: ThemeDefinition = {
  id: 'solarized',
  name: 'Solarized',
  description: 'Precision colors for machines and people',
  author: 'Ethan Schoonover',
  previewColors: {
    primary: '#268bd2',
    secondary: '#2aa198',
    accent: '#859900'
  },
  light: {
    background: '#fdf6e3',    // base3
    foreground: '#657b83',    // base00
    card: '#eee8d5',          // base2
    cardForeground: '#657b83',
    popover: '#eee8d5',       // base2
    popoverForeground: '#657b83',
    primary: '#268bd2',       // blue
    primaryForeground: '#fdf6e3',
    secondary: '#93a1a1',     // base1
    secondaryForeground: '#586e75',
    muted: '#eee8d5',         // base2
    mutedForeground: '#839496', // base0
    accent: '#859900',        // green
    accentForeground: '#fdf6e3',
    destructive: '#dc322f',   // red
    destructiveForeground: '#fdf6e3',
    border: '#d3d7d7',        // lighter version of base1
    input: '#eee8d5',         // base2
    ring: '#268bd2',          // blue
    chart1: '#859900',        // green
    chart2: '#b58900',        // yellow
    chart3: '#268bd2',        // blue
    chart4: '#6c71c4',        // violet
    chart5: '#d33682',        // magenta
    sidebar: '#eee8d5',       // base2
    sidebarForeground: '#657b83',
    sidebarPrimary: '#268bd2',
    sidebarPrimaryForeground: '#fdf6e3',
    sidebarAccent: '#859900',
    sidebarAccentForeground: '#fdf6e3',
    sidebarBorder: '#d3d7d7',
    sidebarRing: '#268bd2',
    serviceBg: '#fdf6e3'
  },
  dark: {
    background: '#002b36',    // base03
    foreground: '#839496',    // base0
    card: '#073642',          // base02
    cardForeground: '#839496',
    popover: '#073642',       // base02
    popoverForeground: '#839496',
    primary: '#268bd2',       // blue
    primaryForeground: '#002b36',
    secondary: '#586e75',     // base01
    secondaryForeground: '#93a1a1',
    muted: '#073642',         // base02
    mutedForeground: '#657b83', // base00
    accent: '#859900',        // green
    accentForeground: '#002b36',
    destructive: '#dc322f',   // red
    destructiveForeground: '#839496',
    border: 'rgba(255,255,255,.1)',        // lighter version of base01
    input: '#073642',         // base02
    ring: '#268bd2',          // blue
    chart1: '#859900',        // green
    chart2: '#b58900',        // yellow
    chart3: '#268bd2',        // blue
    chart4: '#6c71c4',        // violet
    chart5: '#d33682',        // magenta
    sidebar: '#073642',       // base02
    sidebarForeground: '#839496',
    sidebarPrimary: '#268bd2',
    sidebarPrimaryForeground: '#002b36',
    sidebarAccent: '#859900',
    sidebarAccentForeground: '#002b36',
    sidebarBorder: 'rgba(255,255,255,.1)',        // lighter version of base01
    sidebarRing: '#268bd2',
    serviceBg: '#002b36'
  }
}
