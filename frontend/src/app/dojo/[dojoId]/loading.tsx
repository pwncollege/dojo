import { Skeleton } from '@/components/ui/skeleton'

export default function DojoLoading() {
  return (
    <div className="min-h-screen bg-background">
      {/* Main content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Back button */}
        <div className="flex items-center gap-4 mb-8">
          <Skeleton className="h-10 w-32" />
        </div>

        {/* Dojo hero section */}
        <div className="mb-12 relative">
          <div className="absolute top-0 right-0">
            <Skeleton className="h-16 w-16" />
          </div>
          <div className="pr-20">
            <Skeleton className="h-10 w-80 mb-3" />
            <div className="flex items-center gap-3 mb-4">
              <Skeleton className="h-6 w-16" />
              <Skeleton className="h-6 w-24" />
              <Skeleton className="h-6 w-20" />
            </div>
            <Skeleton className="h-20 w-full max-w-3xl" />
          </div>
        </div>

        {/* Stats cards */}
        <div className="grid gap-6 md:grid-cols-4 mb-12">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
              <div className="flex items-center gap-3 mb-2">
                <Skeleton className="h-5 w-5" />
                <Skeleton className="h-5 w-20" />
              </div>
              <Skeleton className="h-8 w-12" />
            </div>
          ))}
        </div>

        {/* Modules section */}
        <div className="mb-12">
          <Skeleton className="h-8 w-32 mb-6" />
          <div className="space-y-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="rounded-lg border bg-card text-card-foreground shadow-sm hover:shadow-md transition-shadow p-6">
                <div className="flex items-center justify-between">
                  <div className="space-y-2 flex-1">
                    <Skeleton className="h-6 w-48" />
                    <Skeleton className="h-16 w-full max-w-2xl" />
                    <div className="flex items-center gap-4 pt-2">
                      <Skeleton className="h-4 w-24" />
                      <Skeleton className="h-4 w-32" />
                    </div>
                  </div>
                  <Skeleton className="h-10 w-32 ml-6" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}