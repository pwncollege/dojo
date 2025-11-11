import { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { useWorkspaceStore } from "@/stores";
import { ArrowDownToDot } from "lucide-react";
import { PROTOCOL } from "@/services/api";

interface WorkspaceServiceProps {
  iframeSrc: string;
  onReady?: () => void;
}

export function WorkspaceService({
  iframeSrc,
  onReady,
}: WorkspaceServiceProps) {
  // Get state from workspace store
  const activeService = useWorkspaceStore((state) => state.activeService);
  const isFullScreen = useWorkspaceStore((state) => state.isFullScreen);
  const sidebarCollapsed = useWorkspaceStore((state) => state.sidebarCollapsed);
  const sidebarWidth = useWorkspaceStore((state) => state.sidebarWidth);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [referenceRect, setReferenceRect] = useState<DOMRect | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const referenceRef = useRef<HTMLDivElement>(null);
  const checkIntervalRef = useRef<NodeJS.Timeout | undefined>(undefined);
  const retryCount = useRef(0);

  const maxRetries = 30; // 30 seconds
  const checkInterval = 1000; // Check every second

  // Update reference div position for portal positioning
  useEffect(() => {
    const updateRect = () => {
      if (referenceRef.current) {
        const rect = referenceRef.current.getBoundingClientRect();
        console.log("Reference rect:", rect);
        setReferenceRect(rect);
      }
    };

    // Use requestAnimationFrame to ensure DOM is ready
    const rafId = requestAnimationFrame(updateRect);

    window.addEventListener("resize", updateRect);
    window.addEventListener("scroll", updateRect);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", updateRect);
      window.removeEventListener("scroll", updateRect);
    };
  }, []);

  useEffect(() => {
    const fullUrl = `${PROTOCOL}://${process.env.NEXT_PUBLIC_DOJO_HOST}${iframeSrc}`

    // Check if iframe already has the correct URL - if so, don't reload
    if (iframeRef.current && iframeRef.current.src === fullUrl && isReady) {
      return;
    }

    setIsLoading(true);
    setError(null);
    setIsReady(false);
    retryCount.current = 0;

    // Check if service is actually ready by making a HEAD request
    const checkServiceReady = async () => {
      retryCount.current++;

      if (retryCount.current >= maxRetries) {
        setError(
          `${activeService} service timed out after ${maxRetries} seconds`,
        );
        setIsLoading(false);
        if (checkIntervalRef.current) {
          clearInterval(checkIntervalRef.current);
        }
        return;
      }

      try {
        // Make a HEAD request to check if service is ready
        const response = await fetch(fullUrl, {
          method: "HEAD",
          credentials: "include", // Include cookies for authentication
        });

        if (response.ok) {
          // Service is ready, load it in iframe
          if (iframeRef.current) {
            console.log("Setting iframe src to:", fullUrl);
            iframeRef.current.src = fullUrl;
          }

          setIsLoading(false);
          // Add small delay to ensure iframe content is rendered before hiding spinner
          setTimeout(() => {
            setIsReady(true);
            setError(null);
            onReady?.();
          }, 100);

          if (checkIntervalRef.current) {
            clearInterval(checkIntervalRef.current);
          }
        } else if (response.status === 502 || response.status === 503) {
          // Service not ready yet, keep checking
        } else {
          // Unexpected error
          console.error(
            `${activeService} service returned unexpected status: ${response.status}`,
          );
        }
      } catch (err) {
        // Network error or CORS issue - try loading iframe anyway after a few attempts
        if (retryCount.current > 3) {
          if (iframeRef.current) {
            console.log("Setting iframe src (fallback) to:", fullUrl);
            iframeRef.current.src = fullUrl;
          }

          setIsLoading(false);
          // Add small delay to ensure iframe content is rendered before hiding spinner
          setTimeout(() => {
            setIsReady(true);
            setError(null);
            onReady?.();
          }, 100);

          if (checkIntervalRef.current) {
            clearInterval(checkIntervalRef.current);
          }
        }
      }
    };

    // Start checking immediately
    checkServiceReady();
    checkIntervalRef.current = setInterval(checkServiceReady, checkInterval);

    return () => {
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
      }
    };
  }, [iframeSrc, activeService, onReady]);

  const isResizing = useWorkspaceStore((state) => state.isResizing);

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full overflow-hidden"
      style={{
        backgroundColor:
          activeService === "terminal"
            ? "var(--service-bg)"
            : "var(--background)",
      }}
    >
      {/* Iframe container with GPU acceleration */}
      <div
        className="absolute inset-0"
        style={{
          // transform: isResizing ? "scale(0.98)" : "scale(1)",
          // opacity: isResizing ? 0.8 : 1,
          // filter: isResizing ? "blur(2px)" : "none",
          transition: "transform 150ms cubic-bezier(0.4, 0, 0.2, 1), opacity 150ms ease-out, filter 150ms ease-out",
          willChange: "transform, opacity, filter",
          backfaceVisibility: "hidden",
          perspective: 1000,
        }}
      >
        <iframe
          ref={iframeRef}
          className={`w-full h-full border-0 ${
            activeService === "code" ? "" : "rounded-lg"
          } ${isReady ? "opacity-100" : "opacity-0"}`}
          style={{
            pointerEvents: isResizing ? "none" : "auto",
            backgroundColor:
              activeService === "terminal"
                ? "var(--service-bg)"
                : "var(--background)",
            transform: "translateZ(0)", // Force GPU layer
          }}
          title={`Workspace ${activeService}`}
          allow="clipboard-write"
        />
      </div>

      {/* Resizing overlay - optimized for performance */}
      {/*<div
        className="absolute inset-0 flex items-center justify-center pointer-events-none"
        style={{
          opacity: isResizing ? 1 : 0,
          transform: isResizing ? "scale(1)" : "scale(0.9)",
          transition: "opacity 150ms ease-out, transform 150ms cubic-bezier(0.4, 0, 0.2, 1)",
          willChange: "opacity, transform",
        }}
      >
        <div clasName="text-center">
          <ArrowDownToDot className="w-16 h-16 text-primary animate-pulse mx-auto mb-4" />
          <p className="text-lg font-medium">Resizing...</p>
        </div>
      </div>
              */}

      {/* Loading overlay when not ready */}
      {!isReady && (
        <motion.div
          className="absolute inset-0 flex items-center justify-center"
          style={{
            backgroundColor:
              activeService === "terminal"
                ? "var(--service-bg)"
                : "var(--background)",
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="text-center">
            {isLoading ? (
              <>
                <div className="w-16 h-16 border-4 border-muted border-t-primary rounded-full animate-spin mx-auto mb-4" />
                <p className="text-lg font-medium">
                  Loading {activeService}...
                </p>
                <p className="text-sm text-muted-foreground mt-2">
                  {activeService === "code" && "Starting VS Code environment"}
                  {activeService === "terminal" &&
                    "Initializing terminal session"}
                  {activeService === "desktop" &&
                    "Setting up desktop environment"}
                </p>
              </>
            ) : error ? (
              <>
                <div className="w-16 h-16 bg-destructive/10 rounded-full flex items-center justify-center mx-auto mb-4">
                  <span className="text-destructive text-2xl">⚠</span>
                </div>
                <p className="text-lg font-medium text-destructive">
                  Failed to load {activeService}
                </p>
                <p className="text-sm text-muted-foreground mt-2">{error}</p>
              </>
            ) : null}
          </div>
        </motion.div>
      )}
    </div>
  );
}
