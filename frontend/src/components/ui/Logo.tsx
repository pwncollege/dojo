import Link from 'next/link'
import { cn } from '@/lib/utils'

interface LogoProps {
  className?: string
  linkClassName?: string
  textClassName?: string
  showFullName?: boolean
}

export function Logo({
  className,
  linkClassName,
  textClassName,
  showFullName = false
}: LogoProps) {
  return (
    <Link
      href="/"
      className={cn(
        "flex items-center space-x-2 group transition-all duration-200 hover:opacity-80",
        linkClassName
      )}
    >
      {/* pwn.college logo text */}
      <div className={cn("flex items-center", className)}>
        <span className={cn(
          "text-xl font-black tracking-widest text-foreground",
          "group-hover:text-primary transition-colors duration-200",
          "[font-family:'JetBrains_Mono','SF_Mono',Monaco,'Cascadia_Code','Roboto_Mono','Consolas','Courier_New',monospace]",
          "[font-feature-settings:'liga'_0,'calt'_0] [text-rendering:geometricPrecision]",
          textClassName
        )}>
          pwn
          <span className="relative mx-1">
            <span className="absolute bg-foreground rounded-sm" style={{inset: 'calc(var(--spacing) * -0.1)', left: '-2px'}}></span>
            <span className="relative text-background">.</span>
          </span>
          college
        </span>
        {showFullName && (
          <span className={cn(
            "ml-2 text-sm font-medium text-muted-foreground",
            "group-hover:text-foreground transition-colors duration-200"
          )}>
            DOJO
          </span>
        )}
      </div>
    </Link>
  )
}

// Compact version for smaller spaces
export function CompactLogo({ className, linkClassName }: { className?: string, linkClassName?: string }) {
  return (
    <Logo
      className={className}
      linkClassName={linkClassName}
      textClassName="text-lg"
      showFullName={false}
    />
  )
}