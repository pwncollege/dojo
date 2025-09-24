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

  const palette = localStorage.getItem('theme-palette') || 'everforest';
  const mode = localStorage.getItem('dojo-ui-theme') || 'system';

  let resolvedMode = mode;
  if (mode === 'system') {
    resolvedMode = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  document.documentElement.classList.add(resolvedMode === 'dark' ? 'dark' : 'light');

  const theme = themes[palette] || themes.everforest;
  if (!theme) return;

  const colors = resolvedMode === 'dark' ? theme.dark : theme.light;

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