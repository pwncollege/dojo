import { useState, useEffect } from "react";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Markdown } from "@/components/ui/markdown";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  BookOpen,
  FileText,
  Play,
  Presentation,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import { useAnimations } from "@/stores";
import type { Resource } from "@/types/api";

interface ResourceViewerProps {
  resource: Resource;
  activeTab?: string;
  onClose?: () => void;
  className?: string;
}

export function ResourceViewer({
  resource,
  activeTab: externalActiveTab,
  onClose,
  className,
}: ResourceViewerProps) {
  const animations = useAnimations();
  const [internalActiveTab, setInternalActiveTab] = useState<"video" | "slides" | "reading">("video");

  // Ignore header type resources - only render markdown and lecture
  if (resource.type === "header") {
    return null;
  }

  const hasVideo = resource.type === "lecture" && resource.video;
  const hasSlides = resource.type === "lecture" && resource.slides;
  const isMarkdown = resource.type === "markdown";

  // Use external tab if provided, otherwise use internal state
  const activeTab = externalActiveTab || internalActiveTab;

  // Auto-select the appropriate tab based on available content
  useEffect(() => {
    const newTab = hasVideo ? "video" : hasSlides ? "slides" : isMarkdown ? "reading" : "video";
    if (!externalActiveTab) {
      setInternalActiveTab(newTab);
    }
  }, [resource.id, hasVideo, hasSlides, isMarkdown, externalActiveTab]);

  return (
    <div className={cn("h-full", className)}>
      {/* Content Area - tabs are in the header */}
      <div className="h-full">
        <AnimatePresence mode="wait">
          {/* Video Content */}
          {hasVideo && activeTab === "video" && (
            <motion.div
              key="video"
              className="w-full h-full"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: animations.medium }}
            >
              <iframe
                src={`https://www.youtube.com/embed/${resource.video}?rel=0&modestbranding`}
                 frameBorder={0}
                className="w-full h-full"
                title={resource.name}
                allowFullScreen
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              />
            </motion.div>
          )}

          {/* Slides Content */}
          {hasSlides && activeTab === "slides" && (
            <motion.div
              key="slides"
              className="h-full"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: animations.medium }}
            >
              <iframe
                src={`https://docs.google.com/presentation/d/${resource.slides}/embed?start=false&loop=false&delayms=3000`}
                className="w-full h-full"
                title={`${resource.name} - Slides`}
                allowFullScreen
              />
            </motion.div>
          )}

          {/* Markdown Reading Content */}
          {isMarkdown && resource.content && activeTab === "reading" && (
            <motion.div
              key="reading"
              className="h-full"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: animations.medium }}
            >
              <ScrollArea className="h-full">
                <div className="max-w-4xl mx-auto p-8">
                  <Card className="overflow-hidden border-primary/10">
                    {/* Reading Header */}
                    <div className="bg-gradient-to-r from-primary/10 to-primary/5 px-8 py-6 border-b">
                      <div className="flex items-center gap-3">
                        <div className="p-2.5 rounded-lg bg-background/80 shadow-sm">
                          <BookOpen className="h-5 w-5 text-primary" />
                        </div>
                        <div>
                          <h2 className="text-lg font-semibold">
                            Reading Material
                          </h2>
                          <p className="text-sm text-muted-foreground mt-0.5">
                            Study at your own pace
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Content */}
                    <div className="p-8 bg-card/50">
                      <div className="prose prose-sm dark:prose-invert max-w-none">
                        <Markdown>{resource.content}</Markdown>
                      </div>
                    </div>
                  </Card>
                </div>
              </ScrollArea>
            </motion.div>
          )}

          {/* Empty State */}
          {!hasVideo && !hasSlides && (!isMarkdown || !resource.content) && (
            <motion.div
              className="h-full flex items-center justify-center"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: animations.medium }}
            >
              <div className="text-center">
                <div className="w-20 h-20 rounded-full bg-muted/50 flex items-center justify-center mx-auto mb-4">
                  <BookOpen className="h-10 w-10 text-muted-foreground" />
                </div>
                <h3 className="text-xl font-semibold mb-2">
                  No Content Available
                </h3>
                <p className="text-sm text-muted-foreground max-w-sm">
                  This resource doesn't have any viewable content yet. Please
                  check back later or contact your instructor.
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
