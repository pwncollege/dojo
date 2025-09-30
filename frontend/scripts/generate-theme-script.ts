import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'
import { dirname } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

function generateThemeScript() {
  const themesDir = path.join(__dirname, '../src/themes/definitions')
  const themeFiles = fs.readdirSync(themesDir).filter(f => f.endsWith('.ts'))

  const themes: Record<string, any> = {}

  for (const file of themeFiles) {
    const filePath = path.join(themesDir, file)
    const content = fs.readFileSync(filePath, 'utf-8')

    const themeIdMatch = content.match(/id:\s*['"]([^'"]+)['"]/)?.[1]
    if (!themeIdMatch) continue

    const lightMatch = content.match(/light:\s*{([^}]+(?:{[^}]+}[^}]+)*?)}/)?.[1]
    const darkMatch = content.match(/dark:\s*{([^}]+(?:{[^}]+}[^}]+)*?)}/)?.[1]

    if (!lightMatch || !darkMatch) continue

    const parseColors = (str: string) => {
      const colors: Record<string, string> = {}
      const lines = str.split('\n')

      for (const line of lines) {
        const match = line.match(/^\s*(\w+):\s*['"]([^'"]+)['"]/);
        if (match) {
          const [, key, value] = match
          const camelKey = key.replace(/([A-Z])/g, (m) => m[0].toUpperCase() + m.slice(1).toLowerCase())
          colors[camelKey] = value
        }
      }

      return colors
    }

    themes[themeIdMatch] = {
      light: parseColors(lightMatch),
      dark: parseColors(darkMatch)
    }
  }

  const script = `
(function() {
  const themes = ${JSON.stringify(themes, null, 2).replace(/"(\w+)":/g, '$1:')};

  const palette = localStorage.getItem('theme-palette') || 'amethyst';
  const mode = localStorage.getItem('dojo-ui-theme') || 'system';

  let resolvedMode = mode;
  if (mode === 'system') {
    resolvedMode = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  document.documentElement.classList.add(resolvedMode === 'dark' ? 'dark' : 'light');

  const theme = themes[palette] || themes.amethyst;
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

  const outputPath = path.join(__dirname, '../src/generated/theme-script.ts')
  const outputDir = path.dirname(outputPath)

  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true })
  }

  fs.writeFileSync(outputPath, `// This file is auto-generated. Do not edit manually.
// Run 'bun run generate-themes' to regenerate.

export const themeScript = \`${script.replace(/`/g, '\\`')}\`;
`)

  console.log('✅ Theme script generated successfully')
}

generateThemeScript()