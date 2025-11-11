import { Loader2 } from "lucide-react";

export default function WorkspaceLoading() {
  return (
    <div className="fixed inset-0 w-full h-full z-40 bg-background">
      <div className="flex items-center justify-center h-full">
        <div className="text-center space-y-4">
                <div className="w-16 h-16 border-4 border-muted border-t-primary rounded-full animate-spin mx-auto mb-4" />
          <p className="text-muted-foreground">Loading workspace...</p>
        </div>
      </div>
    </div>
  )
}
