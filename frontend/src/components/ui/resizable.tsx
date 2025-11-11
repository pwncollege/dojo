import { GripVertical } from "lucide-react"
import * as ResizablePrimitive from "react-resizable-panels"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

import { cn } from "@/lib/utils"

const ResizablePanelGroup = ({
  className,
  ...props
}: React.ComponentProps<typeof ResizablePrimitive.PanelGroup>) => (
  <ResizablePrimitive.PanelGroup
    className={cn(
      "flex h-full w-full data-[panel-group-direction=vertical]:flex-col",
      className
    )}
    {...props}
  />
)

const ResizablePanel = ResizablePrimitive.Panel

const ResizableHandle = ({
  withHandle,
  className,
  onDoubleClick,
  onMouseDown,
  ...props
}: React.ComponentProps<typeof ResizablePrimitive.PanelResizeHandle> & {
  withHandle?: boolean
  onDoubleClick?: () => void
  onMouseDown?: (e: React.MouseEvent) => void
}) => (
  <Tooltip delayDuration={0}>
    <TooltipTrigger asChild>
      <ResizablePrimitive.PanelResizeHandle
        className={cn(
          "relative flex w-px items-center justify-center bg-border after:absolute after:inset-y-0 after:left-1/2 after:w-1 after:-translate-x-1/2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-1 data-[panel-group-direction=vertical]:h-px data-[panel-group-direction=vertical]:w-full data-[panel-group-direction=vertical]:after:left-0 data-[panel-group-direction=vertical]:after:h-1 data-[panel-group-direction=vertical]:after:w-full data-[panel-group-direction=vertical]:after:-translate-y-1/2 data-[panel-group-direction=vertical]:after:translate-x-0 [&[data-panel-group-direction=vertical]>div]:rotate-90",
          // Enhanced hover effects
          "hover:bg-primary/20 hover:after:bg-primary/30 transition-colors duration-200",
          "group cursor-col-resize",
          className
        )}
        onDoubleClick={onDoubleClick}
        onMouseDown={onMouseDown}
        {...props}
      >
        {withHandle && (
          <div className="z-10 flex h-4 w-3 items-center justify-center rounded-sm border bg-border group-hover:bg-primary/10 group-hover:border-primary/30 transition-colors duration-200">
            <GripVertical className="h-2.5 w-2.5 text-muted-foreground group-hover:text-primary transition-colors duration-200" />
          </div>
        )}
      </ResizablePrimitive.PanelResizeHandle>
    </TooltipTrigger>
    <TooltipContent
      side="right"
      className="animate-in fade-in-0 zoom-in-95 slide-in-from-left-2 duration-200 ease-out"
      sideOffset={8}
    >
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-1.5">
          <GripVertical className="h-3 w-3 opacity-60" />
          <span className="text-xs font-medium">Resize</span>
        </div>
        <span className="text-[10px] text-muted-foreground">Double-click to toggle</span>
      </div>
    </TooltipContent>
  </Tooltip>
)

export { ResizablePanelGroup, ResizablePanel, ResizableHandle }