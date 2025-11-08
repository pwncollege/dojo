import { Skeleton } from '@/components/ui/skeleton'

export default function HomeLoading() {
  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Hero Section Skeleton */}
        <div className="py-16 sm:py-20 lg:py-24">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
            <div className="max-w-4xl">
              <Skeleton className="h-12 sm:h-14 lg:h-16 w-full max-w-md mb-6" />
              <Skeleton className="h-6 sm:h-7 lg:h-8 w-full mb-3" />
              <Skeleton className="h-6 sm:h-7 lg:h-8 w-4/5 mb-3" />
              <Skeleton className="h-6 sm:h-7 lg:h-8 w-3/4 mb-8" />
              <Skeleton className="h-4 sm:h-5 w-32" />
            </div>
            <div className="flex justify-center lg:justify-end">
              <Skeleton className="w-[400px] h-[400px] sm:w-80 sm:h-80 lg:w-[600px] lg:h-[600px] rounded-full" />
            </div>
          </div>
        </div>

        {/* Section Header Skeleton */}
        <div className="mb-12">
          <div className="flex items-center gap-3 mb-4">
            <Skeleton className="h-8 w-8 rounded" />
            <Skeleton className="h-8 w-48" />
          </div>
          <Skeleton className="h-6 w-64 mb-2" />
          <Skeleton className="h-5 w-96" />
        </div>

        {/* Dojos Grid Skeleton */}
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3 pb-16">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="rounded-lg border bg-card p-6">
              <div className="flex items-start justify-between mb-4">
                <div className="space-y-2 flex-1">
                  <Skeleton className="h-6 w-36" />
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-4 w-16 rounded-full" />
                    <Skeleton className="h-4 w-20" />
                  </div>
                </div>
                <Skeleton className="h-12 w-16" />
              </div>

              <Skeleton className="h-4 w-full mb-2" />
              <Skeleton className="h-4 w-5/6 mb-2" />
              <Skeleton className="h-4 w-4/5 mb-6" />

              <div className="flex gap-4 mb-4">
                <Skeleton className="h-5 w-24" />
                <Skeleton className="h-5 w-28" />
              </div>

              <Skeleton className="h-px w-full mb-2" />

              <div className="flex items-center justify-between pt-2">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-3 w-3" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}