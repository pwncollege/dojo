import type { ThemeDefinition } from '../types'

export const defaultTheme: ThemeDefinition = {
  id: 'default',
  name: 'Default',
  description: 'Official pwn.college colors',
  author: 'pwn.college',
  previewColors: {
    primary: '#FFA500',
    secondary: '#9ACD32',
    accent: '#00BFFF'
  },
  light: {
    background: '#FFFFFF',
    foreground: '#1A1A1A',
    card: '#F5F5F5',
    cardForeground: '#1A1A1A',
    popover: '#FFFFFF',
    popoverForeground: '#1A1A1A',
    primary: '#FFA500',       // pwn.college orange
    primaryForeground: '#FFFFFF',
    secondary: '#F5F5F5',
    secondaryForeground: '#1A1A1A',
    muted: '#F5F5F5',
    mutedForeground: '#6B7280',
    accent: '#9ACD32',        // pwn.college green
    accentForeground: '#1A1A1A',
    destructive: '#DC2626',
    destructiveForeground: '#FFFFFF',
    success: '#16A34A',
    successForeground: '#FFFFFF',
    border: '#E5E7EB',
    input: '#E5E7EB',
    ring: '#FFA500',
    chart1: '#FFA500',        // orange
    chart2: '#9ACD32',        // green
    chart3: '#00BFFF',        // blue
    chart4: '#9370DB',        // purple
    chart5: '#FF69B4',        // pink
    sidebar: '#F9FAFB',
    sidebarForeground: '#1A1A1A',
    sidebarPrimary: '#FFA500',
    sidebarPrimaryForeground: '#FFFFFF',
    sidebarAccent: '#9ACD32',
    sidebarAccentForeground: '#1A1A1A',
    sidebarBorder: '#E5E7EB',
    sidebarRing: '#FFA500',
    serviceBg: '#FFFFFF'
  },
  dark: {
    background: '#1A1A1A',    // dark background from screenshot
    foreground: '#E5E7EB',
    card: '#262626',
    cardForeground: '#E5E7EB',
    popover: '#262626',
    popoverForeground: '#E5E7EB',
    primary: '#FFA500',       // pwn.college orange
    primaryForeground: '#1A1A1A',
    secondary: '#404040',
    secondaryForeground: '#E5E7EB',
    muted: '#404040',
    mutedForeground: '#9CA3AF',
    accent: '#9ACD32',        // pwn.college green
    accentForeground: '#1A1A1A',
    destructive: '#EF4444',
    destructiveForeground: '#FFFFFF',
    success: '#22C55E',
    successForeground: '#1A1A1A',
    border: '#404040',
    input: '#262626',
    ring: '#FFA500',
    chart1: '#FFA500',        // orange
    chart2: '#9ACD32',        // green
    chart3: '#00BFFF',        // blue
    chart4: '#9370DB',        // purple
    chart5: '#FF69B4',        // pink
    sidebar: '#0D0D0D',       // darker than main background
    sidebarForeground: '#E5E7EB',
    sidebarPrimary: '#FFA500',
    sidebarPrimaryForeground: '#1A1A1A',
    sidebarAccent: '#9ACD32',
    sidebarAccentForeground: '#1A1A1A',
    sidebarBorder: '#404040',
    sidebarRing: '#FFA500',
    serviceBg: '#2B2B2B'
  }
}
