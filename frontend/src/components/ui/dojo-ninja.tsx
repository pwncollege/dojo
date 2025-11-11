'use client'

import Image from 'next/image'
import { useTheme } from '@/components/theme/ThemeProvider'
import { getThemeFilter } from '@/lib/theme-filters'
import { cn } from '@/lib/utils'
import ninjaImage from '@/assets/ninja.png'

interface DojoNinjaProps {
  className?: string
  width?: number
  height?: number
  alt?: string
  priority?: boolean
}

export function DojoNinja({
  className,
  width = 600,
  height = 600,
  alt = "Security Ninja",
  priority = false
}: DojoNinjaProps) {
  const { palette } = useTheme()
  const ninjaFilter = getThemeFilter(palette)

  return (
    <Image
      src={ninjaImage}
      alt={alt}
      width={width}
      height={height}
      priority={priority}
      className={cn(
        "transition-all duration-500 aspect-square object-contain",
        className
      )}
      style={{ filter: ninjaFilter }}
    />
  )
}