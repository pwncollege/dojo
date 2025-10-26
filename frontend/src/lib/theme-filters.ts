// Hue rotation values for each theme to colorize the ninja icon
export const themeHueRotations: Record<string, number> = {
  amethyst: 270,    // Purple tones
  everforest: 120,  // Green tones
  gruvbox: 30,      // Orange/brown tones
  solarized: 180,   // Cyan tones
  matrix: 90,       // Bright green tones
  perplexity: 155,  // Bright cyan tones
}

// Get the CSS filter string for hue rotation based on theme
export function getThemeFilter(themeId: string): string {
  const rotation = themeHueRotations[themeId] || 0
  return rotation ? `hue-rotate(${rotation}deg)` : 'none'
}

// Get the hue rotation value for a theme
export function getThemeHueRotation(themeId: string): number {
  return themeHueRotations[themeId] || 0
}