import type { ThemeDefinition } from '../types'

export const everforestTheme: ThemeDefinition = {
  id: 'everforest',
  name: 'Everforest',
  description: 'Green forest-inspired theme',
  author: 'sainnhe',
  previewColors: {
    primary: '#8da101',
    secondary: '#a7c080',
    accent: '#7fbbb3'
  },
  light: {
    background: '#fdf6e3',  // bg0
    foreground: '#5c6a72',  // fg
    card: '#f4f0d9',        // bg1
    cardForeground: '#5c6a72',
    popover: '#f4f0d9',     // bg1
    popoverForeground: '#5c6a72',
    primary: '#8da101',     // green
    primaryForeground: '#fdf6e3',
    secondary: '#bdc3af',   // bg5
    secondaryForeground: '#5c6a72',
    muted: '#efebd4',       // bg2
    mutedForeground: '#829181',  // grey2
    accent: '#3a94c5',      // blue
    accentForeground: '#fdf6e3',
    destructive: '#f85552', // red
    destructiveForeground: '#fdf6e3',
    success: '#8da101',     // green
    successForeground: '#fdf6e3',
    border: '#e6e2cc',      // bg3
    input: '#efebd4',       // bg2
    ring: '#8da101',        // green
    chart1: '#8da101',      // green
    chart2: '#f57d26',      // orange
    chart3: '#35a77c',      // aqua
    chart4: '#df69ba',      // purple
    chart5: '#3a94c5',      // blue
    sidebar: '#f4f0d9',     // bg1
    sidebarForeground: '#5c6a72',
    sidebarPrimary: '#8da101',
    sidebarPrimaryForeground: '#fdf6e3',
    sidebarAccent: '#3a94c5',
    sidebarAccentForeground: '#fdf6e3',
    sidebarBorder: '#e0dcc7',  // bg4
    sidebarRing: '#8da101',
    serviceBg: '#fdf6e3'
  },
  dark: {
    background: '#2d353b',  // bg0
    foreground: '#d3c6aa',  // fg
    card: '#343f44',        // bg1
    cardForeground: '#d3c6aa',
    popover: '#343f44',     // bg1
    popoverForeground: '#d3c6aa',
    primary: '#a7c080',     // green
    primaryForeground: '#2d353b',
    secondary: '#56635f',   // bg5
    secondaryForeground: '#d3c6aa',
    muted: '#3d484d',       // bg2
    mutedForeground: '#9da9a0',  // grey2
    accent: '#7fbbb3',      // blue
    accentForeground: '#2d353b',
    destructive: '#e67e80', // red
    destructiveForeground: '#d3c6aa',
    success: '#a7c080',     // green
    successForeground: '#2d353b',
    border: '#475258',      // bg3
    input: '#3d484d',       // bg2
    ring: '#a7c080',        // green
    chart1: '#a7c080',      // green
    chart2: '#e69875',      // orange
    chart3: '#83c092',      // aqua
    chart4: '#d699b6',      // purple
    chart5: '#7fbbb3',      // blue
    sidebar: '#232a2e',     // bg_dim
    sidebarForeground: '#d3c6aa',
    sidebarPrimary: '#a7c080',
    sidebarPrimaryForeground: '#2d353b',
    sidebarAccent: '#7fbbb3',
    sidebarAccentForeground: '#2d353b',
    sidebarBorder: '#4f585e',  // bg4
    sidebarRing: '#a7c080',
    serviceBg: '#232A2E'
  }
}
