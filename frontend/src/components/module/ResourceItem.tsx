"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Markdown } from "@/components/ui/markdown";
import { StartResourceButton } from "@/components/ui/start-resource-button";
import { Video, FileText, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";

interface Resource {
  id: string;
  name: string;
  type: "markdown" | "lecture" | "header";
  content?: string;
  video?: string;
  playlist?: string;
  slides?: string;
  expandable?: boolean;
  resource_index?: number;
}

interface ResourceItemProps {
  resource: Resource;
  dojoId: string;
  moduleId: string;
  isOpen: boolean;
  onToggle: () => void;
  isAfterHeader?: boolean;
}

export function ResourceItem({
  resource,
  dojoId,
  moduleId,
  isOpen,
  onToggle,
  isAfterHeader = false,
}: ResourceItemProps) {
  // Header resources render as section headers
  if (resource.type === "header") {
    return (
      <div className="mt-20">
        <h2 className="text-2xl font-bold text-primary">{resource.content}</h2>
      </div>
    );
  }

  // Non-expandable markdown resources render directly
  if (resource.type === "markdown" && resource.expandable === false) {
    return (
      <div className="prose prose-sm dark:prose-invert max-w-none -mt-3 mb-6">
        <Markdown>{resource.content}</Markdown>

      </div>
    );
  }

  // All other resources render as expandable cards
  return (
    <Card
      className={cn(
        "hover:border-primary/50 transition-all duration-200",
        isOpen && "border-primary/30",
      )}
    >
      <CardHeader className="pb-3 pt-4 cursor-pointer group" onClick={onToggle}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {resource.type === "lecture" ? (
              <Video className="h-5 w-5 text-primary" />
            ) : (
              <FileText className="h-5 w-5 text-primary" />
            )}
            <CardTitle className="text-lg group-hover:text-primary transition-colors">
              {resource.name}
            </CardTitle>
            {resource.type === "lecture" && resource.video && (
              <Badge variant="secondary" className="text-xs">
                Video
              </Badge>
            )}
            {resource.type === "lecture" && resource.slides && (
              <Badge variant="secondary" className="text-xs">
                Slides
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-3">
            <motion.div
              animate={{
                opacity: isOpen ? 1 : 0,
                x: isOpen ? 0 : 10,
              }}
              transition={{ duration: 0.2 }}
              className="group-hover:!opacity-100 group-hover:!x-0"
            >
              <StartResourceButton
                dojoId={dojoId}
                moduleId={moduleId}
                resourceId={resource.id}
                resourceType={resource.type}
                size="sm"
                className="gap-2"
              />
            </motion.div>
            <ChevronRight
              className={cn(
                "h-5 w-5 text-muted-foreground transition-transform duration-200",
                isOpen && "rotate-90",
              )}
            />
          </div>
        </div>
      </CardHeader>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            key={`resource-content-${resource.id}`}
            initial={{ height: 0, opacity: 0 }}
            animate={{
              height: "auto",
              opacity: 1,
              transition: {
                height: { duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] },
                opacity: { duration: 0.2, delay: 0.1 },
              },
            }}
            exit={{
              height: 0,
              opacity: 0,
              transition: {
                height: { duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] },
                opacity: { duration: 0.1 },
              },
            }}
            style={{ overflow: "hidden" }}
          >
            <CardContent className="border-t">
              <motion.div
                initial={{ y: -10, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                exit={{ y: -10, opacity: 0 }}
                transition={{ duration: 0.2, delay: 0.1 }}
              >
                {resource.type === "lecture" && resource.video && (
                  <div className="mb-4 mt-5">
                    <div className="aspect-video w-full">
                      <iframe
                        src={`https://www.youtube.com/embed/${resource.video}${resource.playlist ? `?list=${resource.playlist}` : ""}?rel=0`}
                        className="w-full h-full rounded-lg"
                        title="YouTube video player"
                        allowFullScreen
                      />
                    </div>
                  </div>
                )}
                {resource.type === "lecture" && resource.slides && (
                  <div className="">
                    <div className="aspect-video w-full">
                      <iframe
                        src={`https://docs.google.com/presentation/d/${resource.slides}/embed`}
                        className="w-full h-full rounded-lg"
                        allowFullScreen
                      />
                    </div>
                  </div>
                )}
                {resource.type === "markdown" && resource.content && (
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <Markdown>{resource.content}</Markdown>
                  </div>
                )}
              </motion.div>
            </CardContent>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}
