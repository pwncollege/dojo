import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { BookOpen, Zap } from 'lucide-react'
import { Belt } from '@/components/ui/belt'
import { Dojo, SectionInfo } from './home-client'

const getDojoIcon = (dojo: any) => {
  // If dojo has an award with a belt, use the Belt component
  if (dojo.award?.belt && dojo.official) {
    return (
      <Belt
        color={dojo.award.belt}
        alt={`${dojo.award.belt} belt`}
        className="h-6 w-auto max-w-[48px]"
      />
    )
  }

  // If dojo has an award with an emoji, use the emoji
  if (dojo.award?.emoji) {
    return <span className="text-3xl">{dojo.award.emoji}</span>
  }

  // Fallback to name-based emojis
  const name = dojo.name?.toLowerCase() || ''
  if (name.includes('fundamentals')) return <span className="text-3xl">💻</span>
  if (name.includes('linux')) return <span className="text-3xl">🐧</span>
  if (name.includes('program')) return <span className="text-3xl">🔤</span>
  if (name.includes('web')) return <span className="text-3xl">🌐</span>
  if (name.includes('crypto')) return <span className="text-3xl">🔐</span>
  if (name.includes('reverse')) return <span className="text-3xl">🔍</span>
  if (name.includes('pwn')) return <span className="text-3xl">💥</span>
  if (name.includes('forensics')) return <span className="text-3xl">🕵️</span>
  return <span className="text-3xl">🎯</span>
}

const DojoCard = ({
  dojo,
  progress = null,
}: {
  dojo: any
  progress?: number | null
}) => {
  // Don't render if dojo.id is missing
  if (!dojo.id) {
    return null
  }

  return (
    <Link href={`/dojo/${dojo.id}`} className="group">
      <Card className="relative h-full border border-border hover:border-primary/30 hover:bg-primary/5 transition-all duration-200 group-hover:translate-y-[-2px]">
        {/* Icon positioned top-right */}
        <div className="absolute top-4 right-4 flex items-center justify-center">
          {getDojoIcon(dojo)}
        </div>
        <CardHeader className="pb-3 pr-14">
          <CardTitle className="text-lg font-semibold truncate group-hover:text-foreground transition-colors mb-3">
            {dojo.name}
          </CardTitle>
          <div className="flex items-center gap-2 mb-3">
            {dojo.official && (
              <Badge variant="default" className="text-xs">
                Official
              </Badge>
            )}
            {progress !== null && (
              <Badge variant="outline" className="text-xs">
                {progress}%
              </Badge>
            )}
          </div>{' '}
        </CardHeader>

        <CardContent className="pt-0">
          {/* Progress Bar */}
          <div className="mb-4">
            <div className="flex items-center justify-between text-xs mb-2">
              <span className="text-muted-foreground">Progress</span>
              <span className="font-medium text-foreground">
                {progress || 0}%
              </span>
            </div>
            <div className="w-full bg-muted rounded-full h-2">
              <div
                className="bg-primary h-2 rounded-full transition-all duration-300"
                style={{ width: `${progress || 0}%` }}
              />
            </div>
          </div>

          {/* Stats Grid */}
          <div className="space-y-2 mb-4">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Modules</span>
              <span className="font-medium text-foreground">
                {dojo.modules || '-'}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Challenges</span>
              <span className="font-medium text-foreground">
                {dojo.challenges || '-'}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Active Hackers</span>
              <span className="font-medium text-foreground">
                {dojo.active_hackers || '-'}
              </span>
            </div>
          </div>

          {/* Action Indicator */}
          <div className="flex items-center justify-between pt-2 border-t border-border">
            <div className="text-xs text-muted-foreground">Explore course</div>
            <div className="text-xs text-muted-foreground group-hover:text-foreground transition-colors">
              →
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

const SectionHeader = ({
  icon,
  title,
  subtitle,
  description,
}: {
  icon: React.ReactNode
  title: string
  subtitle: string
  description: string
}) => (
  <div className="mb-12">
    <div className="flex items-center gap-3 mb-4">
      {icon}
      <h2 className="text-3xl font-bold">{title}</h2>
    </div>
    <p className="text-xl font-medium text-muted-foreground mb-2">{subtitle}</p>
    <p className="text-muted-foreground leading-relaxed">{description}</p>
  </div>
)

type DojoGridProps = {
  dojos: Dojo[]
  sectionInfo: SectionInfo
}

const DojoGrid = ({ dojos, sectionInfo }: DojoGridProps) => (
  <div className="pt-16 sm:pt-20 pb-16 sm:pb-20">
    <SectionHeader
      icon={<Zap className="h-8 w-8 text-primary" />}
      title={sectionInfo.title}
      subtitle={sectionInfo.subtitle}
      description={sectionInfo.description}
    />
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {dojos.map((dojo) => (
        <DojoCard key={dojo.id} dojo={dojo} progress={0} />
      ))}
    </div>
    {sectionInfo.footer && (
      <div className="mt-8 p-4 bg-muted/30 rounded-lg">
        <p className="text-muted-foreground font-medium">
          {sectionInfo.footer}
        </p>
      </div>
    )}
  </div>
)

const NoDojosState = () => (
  <div className="py-16">
    <BookOpen className="h-16 w-16 text-muted-foreground mb-4" />
    <h3 className="text-xl font-semibold mb-2">No dojos available yet</h3>
    <p className="text-muted-foreground">Check back soon for new challenges!</p>
  </div>
)

export { DojoGrid, NoDojosState }
