import Link from 'next/link'
import Image from 'next/image'
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
        "flex items-center gap-2 group transition-all duration-200",
        linkClassName
      )}
    >
      {/* pwn.college logo with icon in the middle */}
      <div className={cn("flex items-center gap-1", className)}>
        <span className={cn(
          "text-xl font-bold tracking-tight text-foreground",
          "group-hover:text-primary transition-colors duration-200",
          "font-sans",
          textClassName
        )}>
          pwn
        </span>

        {/* Favicon icon between pwn and college */}
        <Image
          src="/favicon.png"
          alt=""
          width={16}
          height={16}
          className="flex-shrink-0 opacity-90 group-hover:opacity-100 transition-opacity mt-1.5"
        />

        <span className={cn(
          "text-xl font-bold tracking-tight text-foreground",
          "group-hover:text-primary transition-colors duration-200",
          "font-sans",
          textClassName
        )}>
          college
        </span>

        {showFullName && (
          <span className={cn(
            "ml-3 text-sm font-semibold text-muted-foreground uppercase tracking-wider",
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