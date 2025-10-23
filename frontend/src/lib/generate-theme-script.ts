import { getAllThemes } from '@/themes'
import { themeColorsToCSSVars } from '@/themes/registry'

export function generateThemeScript(): string {
  const themes = getAllThemes()

  const themeData: Record<string, any> = {}

  for (const theme of themes) {
    themeData[theme.id] = {
      light: theme.light,
      dark: theme.dark
    }
  }

  return `
(function() {
  const themes = ${JSON.stringify(themeData)};

  const palette = localStorage.getItem('theme-palette') || 'default';
  // Always use dark mode (light mode is disabled)
  const resolvedMode = 'dark';

  document.documentElement.classList.add('dark');

  const theme = themes[palette] || themes.default;
  if (!theme) return;

  const colors = theme.dark;

  const root = document.documentElement;

  const cssVarMap = {
    background: '--background',
    foreground: '--foreground',
    card: '--card',
    cardForeground: '--card-foreground',
    popover: '--popover',
    popoverForeground: '--popover-foreground',
    primary: '--primary',
    primaryForeground: '--primary-foreground',
    secondary: '--secondary',
    secondaryForeground: '--secondary-foreground',
    muted: '--muted',
    mutedForeground: '--muted-foreground',
    accent: '--accent',
    accentForeground: '--accent-foreground',
    destructive: '--destructive',
    destructiveForeground: '--destructive-foreground',
    border: '--border',
    input: '--input',
    ring: '--ring',
    chart1: '--chart-1',
    chart2: '--chart-2',
    chart3: '--chart-3',
    chart4: '--chart-4',
    chart5: '--chart-5',
    sidebar: '--sidebar',
    sidebarForeground: '--sidebar-foreground',
    sidebarPrimary: '--sidebar-primary',
    sidebarPrimaryForeground: '--sidebar-primary-foreground',
    sidebarAccent: '--sidebar-accent',
    sidebarAccentForeground: '--sidebar-accent-foreground',
    sidebarBorder: '--sidebar-border',
    sidebarRing: '--sidebar-ring',
    serviceBg: '--service-bg'
  };

  for (const [key, cssVar] of Object.entries(cssVarMap)) {
    if (colors[key]) {
      root.style.setProperty(cssVar, colors[key]);
    }
  }
})();
`.trim()
}