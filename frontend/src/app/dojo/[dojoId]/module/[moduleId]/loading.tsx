import { Skeleton } from '@/components/ui/skeleton'

export default function ModuleLoading() {
  return (
    <div className="min-h-screen bg-background">
      {/* Main content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Back button */}
        <div className="mb-8">
          <Skeleton className="h-10 w-40 mb-4" />

          {/* Module header */}
          <div className="mb-6">
            <Skeleton className="h-10 w-64 mb-2" />
            <div className="flex items-center gap-4">
              <Skeleton className="h-6 w-20" />
              <Skeleton className="h-4 w-32" />
            </div>
          </div>
        </div>

        {/* Module description */}
        <div className="space-y-8">
          <div className="space-y-4">
            <Skeleton className="h-20 w-full" />
          </div>

          {/* Learning Materials */}
          <div className="mt-12">
            <Skeleton className="h-8 w-48 mb-6" />
            <div className="space-y-3">
              {Array.from({ length: 2 }).map((_, i) => (
                <div key={i} className="rounded-lg border bg-card text-card-foreground shadow-sm p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Skeleton className="h-5 w-5" />
                      <Skeleton className="h-5 w-40" />
                      <Skeleton className="h-4 w-12" />
                    </div>
                    <div className="flex items-center gap-3">
                      <Skeleton className="h-8 w-24" />
                      <Skeleton className="h-5 w-5" />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Challenges */}
          <div className="mt-12">
            <Skeleton className="h-8 w-32 mb-6" />
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="rounded-lg border bg-card text-card-foreground shadow-sm p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Skeleton className="h-8 w-8 rounded-full" />
                      <div className="flex items-center gap-2">
                        <Skeleton className="h-4 w-4" />
                        <Skeleton className="h-5 w-48" />
                        <Skeleton className="h-4 w-16" />
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <Skeleton className="h-8 w-20" />
                      <Skeleton className="h-5 w-5" />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}