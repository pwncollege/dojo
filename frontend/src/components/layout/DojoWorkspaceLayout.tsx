"use client";

import {
  useState,
  useEffect,
  useRef,
  useMemo,
  createContext,
  useContext,
} from "react";
import { motion } from "framer-motion";
import { usePathname } from "next/navigation";
import { useWorkspace } from "@/hooks/useWorkspace";
import { useStartChallenge } from "@/hooks/useDojo";
import {
  useWorkspaceStore,
  useWorkspaceService,
  useWorkspaceView,
  useWorkspaceChallenge,
} from "@/stores";
import { CommandPalette } from "@/components/ui/command-palette";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import { useCommands } from "@/hooks/useCommands";
import { useHotkeys, hotkey } from "@/hooks/useHotkeys";
import { WorkspaceSidebar } from "@/components/workspace/WorkspaceSidebar";
import { AnimatedWorkspaceHeader } from "@/components/workspace/AnimatedWorkspaceHeader";
import { WorkspaceContent } from "@/components/workspace/WorkspaceContent";
import { FullscreenHoverHandles } from "@/components/workspace/FullscreenHoverHandles";
import type { Dojo, DojoModule } from "@/types/api";
import { useTheme } from "@/components/theme/ThemeProvider";
const ResourceTabContext = createContext<{
  activeResourceTab: string;
  setActiveResourceTab: (tab: string) => void;
} | null>(null);

export const useResourceTab = () => {
  const context = useContext(ResourceTabContext);
  return context;
};

interface DojoWorkspaceLayoutProps {
  dojo: Dojo;
  modules: DojoModule[];
  onChallengeStart: (
    dojoId: string,
    moduleId: string,
    challengeId: string,
  ) => void;
  onChallengeClose: () => void;
  onResourceSelect?: (resourceId: string | null) => void;
}

export function DojoWorkspaceLayout({
  dojo,
  modules,
  onChallengeStart,
  onChallengeClose,
  onResourceSelect,
}: DojoWorkspaceLayoutProps) {
  // ALL HOOKS MUST BE AT THE TOP - before any conditional returns
  // Use workspace state from dedicated workspace store
  const sidebarCollapsed = useWorkspaceStore((state) => state.sidebarCollapsed);
  const isFullScreen = useWorkspaceStore((state) => state.isFullScreen);
  const isMinimized = useWorkspaceStore((state) => state.isMinimized);
  const sidebarWidth = useWorkspaceStore((state) => state.sidebarWidth);
  const isResizing = useWorkspaceStore((state) => state.isResizing);
  const setIsResizing = useWorkspaceStore((state) => state.setIsResizing);
  const commandPaletteOpen = useWorkspaceStore(
    (state) => state.commandPaletteOpen,
  );
  const workspaceHeaderHidden = useWorkspaceStore(
    (state) => state.headerHidden,
  );

  const setSidebarCollapsed = useWorkspaceStore(
    (state) => state.setSidebarCollapsed,
  );
  const setFullScreen = useWorkspaceStore((state) => state.setFullScreen);
  const setSidebarWidth = useWorkspaceStore((state) => state.setSidebarWidth);
  const setCommandPaletteOpen = useWorkspaceStore(
    (state) => state.setCommandPaletteOpen,
  );
  const setWorkspaceHeaderHidden = useWorkspaceStore(
    (state) => state.setHeaderHidden,
  );
  const setActiveChallenge = useWorkspaceStore(
    (state) => state.setActiveChallenge,
  );

  const { activeService, preferredService, setActiveService } =
    useWorkspaceService();

  // Manage activeResourceTab state for resource content
  const [activeResourceTab, setActiveResourceTab] = useState<string>("video");

  const startChallengeMutation = useStartChallenge();
  const { palette } = useTheme();
  const pathname = usePathname();

  // Parse URL to determine active challenge/resource
  const urlParts = pathname.split("/");
  const workspaceIndex = urlParts.indexOf("workspace");
  const type = urlParts[workspaceIndex + 1]; // 'challenge' or 'resource'
  const id = urlParts[workspaceIndex + 2]; // challengeId or resourceId

  const challengeId = type === "challenge" ? id : undefined;
  const resourceId = type === "resource" ? id : undefined;
  const isResourceMode = !!resourceId;
  const isChallenge = !!challengeId;

  // Get the current module (we only have one in workspace view)
  const currentModule = modules[0];

  // Find active challenge/resource
  const challenge = currentModule?.challenges?.find(
    (c) => c.id === challengeId,
  );
  const resource = currentModule?.resources?.find((r) => r.id === resourceId);

  // Create activeChallenge object for consistency
  const activeChallenge =
    isChallenge && challenge
      ? {
          dojoId: dojo.id,
          moduleId: currentModule.id,
          challengeId: challenge.id,
          name: challenge.name,
        }
      : isResourceMode && resource
        ? {
            dojoId: dojo.id,
            moduleId: currentModule.id,
            challengeId: "resource",
            name: resource.name,
          }
        : undefined;

  // Get the stored active challenge (this is the source of truth for UI)
  const storedActiveChallenge = useWorkspaceStore(state => state.activeChallenge);

  // Set appropriate tab when resource changes
  useEffect(() => {
    if (resource) {
      const hasVideo = resource.type === "lecture" && resource.video;
      const hasSlides = resource.type === "lecture" && resource.slides;
      const isMarkdown = resource.type === "markdown";

      const appropriateTab = hasVideo ? "video" : hasSlides ? "slides" : isMarkdown ? "reading" : "video";
      setActiveResourceTab(appropriateTab);
    }
  }, [resource?.id, setActiveResourceTab]);

  // Pass theme name for terminal and code services
  const serviceTheme =
    activeService === "terminal" || activeService === "code"
      ? palette
      : undefined;

  // Use stored active challenge for workspace query (prioritize store over URL)
  const challengeForWorkspace = storedActiveChallenge || activeChallenge;

  // Single workspace call that gets status and data in one request
  // Only enable when we have an active challenge AND it's not currently starting
  // Include challenge info in query key so it refetches when challenge changes
  const { data: workspaceData } = useWorkspace(
    {
      service: activeService,
      challenge: challengeForWorkspace
        ? `${challengeForWorkspace.dojoId}-${challengeForWorkspace.moduleId}-${challengeForWorkspace.challengeId}`
        : "",
      theme: serviceTheme,
    },
    !!challengeForWorkspace && !challengeForWorkspace?.isStarting,
  );

  // Set active challenge in workspace store for widget (only if URL changed)
  useEffect(() => {
    // Only update if URL-based challenge is different from stored
    if (activeChallenge && (!storedActiveChallenge ||
        storedActiveChallenge.challengeId !== activeChallenge.challengeId)) {
      setActiveChallenge({
        dojoId: activeChallenge.dojoId,
        moduleId: activeChallenge.moduleId,
        challengeId: activeChallenge.challengeId,
        challengeName: activeChallenge.name,
        dojoName: dojo.name,
        moduleName: currentModule.name,
        isStarting: false, // URL navigation means it's not a new start
      });
    }
  }, [activeChallenge, dojo.name, currentModule?.name, setActiveChallenge, storedActiveChallenge]);

  // Handler function for challenge start
  const handleChallengeStart = async (
    moduleId: string,
    challengeId: string,
  ) => {
    // Find the challenge details
    const targetChallenge = currentModule?.challenges?.find(c => c.id === challengeId);
    if (!targetChallenge) return;

    // 1. Immediately update active challenge in store with isStarting flag
    setActiveChallenge({
      dojoId: dojo.id,
      moduleId: moduleId,
      challengeId: challengeId,
      challengeName: targetChallenge.name,
      dojoName: dojo.name,
      moduleName: currentModule.name,
      isStarting: true,
    });

    // 2. Update URL (shallow routing handled in workspace-client)
    onChallengeStart(dojo.id, moduleId, challengeId);

    // 3. Start challenge on server in background
    try {
      await startChallengeMutation.mutateAsync({
        dojoId: dojo.id,
        moduleId,
        challengeId,
        practice: false,
      });
    } catch (error) {
      console.error("Failed to start challenge:", error);
      // Reset isStarting on error
      setActiveChallenge({
        dojoId: dojo.id,
        moduleId: moduleId,
        challengeId: challengeId,
        challengeName: targetChallenge.name,
        dojoName: dojo.name,
        moduleName: currentModule.name,
        isStarting: false,
      });
    }
  };

  // Commands hook
  const commands = useCommands({
    activeChallenge,
    modules: modules.map((m) => ({
      ...m,
      challenges: m.challenges.map((c) => ({ ...c, id: c.id.toString() })),
    })),
    activeService,
    sidebarCollapsed,
    isFullScreen,
    headerHidden: workspaceHeaderHidden,
    setActiveService,
    setSidebarCollapsed,
    setIsFullScreen: setFullScreen,
    setHeaderHidden: setWorkspaceHeaderHidden,
    onChallengeStart: handleChallengeStart,
    onChallengeClose,
  });

  // Setup hotkeys
  useHotkeys(
    {
      [hotkey.ctrlShift("p")]: () => setCommandPaletteOpen(!commandPaletteOpen),
      [hotkey.cmdShift("p")]: () => setCommandPaletteOpen(!commandPaletteOpen),
      [hotkey.ctrl("b")]: () => setSidebarCollapsed(!sidebarCollapsed),
      [hotkey.cmd("b")]: () => setSidebarCollapsed(!sidebarCollapsed),
      [hotkey.ctrl("h")]: () =>
        setWorkspaceHeaderHidden(!workspaceHeaderHidden),
      [hotkey.cmd("h")]: () => setWorkspaceHeaderHidden(!workspaceHeaderHidden),
      ["f11"]: () => setFullScreen(!isFullScreen),
      ["escape"]: () => isFullScreen && setFullScreen(false),
      [hotkey.ctrl("1")]: () =>
        workspaceData?.active && setActiveService("terminal"),
      [hotkey.ctrl("2")]: () =>
        workspaceData?.active && setActiveService("code"),
      [hotkey.ctrl("3")]: () =>
        workspaceData?.active && setActiveService("desktop"),
    },
    [isFullScreen, workspaceData?.active],
  );

  // Auto-expand module and use preferred service
  useEffect(() => {
    if (activeChallenge) {
      setActiveService(preferredService);
      // Don't auto-hide workspace header anymore since we want it visible by default
    }
  }, [activeChallenge?.challengeId, preferredService, setActiveService]);

  // Clear isStarting when workspace becomes active
  useEffect(() => {
    const currentChallenge = useWorkspaceStore.getState().activeChallenge;
    if (workspaceData?.active && currentChallenge?.isStarting) {
      setActiveChallenge({
        ...currentChallenge,
        isStarting: false,
      });
    }
  }, [workspaceData?.active, setActiveChallenge]);

  // Cached Canvas for text measurement (create once, reuse)
  const getTextMeasureCanvas = (() => {
    let canvas: HTMLCanvasElement | null = null;
    let context: CanvasRenderingContext2D | null = null;

    return () => {
      // Only create canvas on client side
      if (typeof document === "undefined") {
        return null;
      }

      if (!canvas || !context) {
        canvas = document.createElement("canvas");
        context = canvas.getContext("2d");
        if (context) {
          context.font = "500 14px Inter, system-ui, sans-serif";
        }
      }
      return context;
    };
  })();

  // Calculate optimal sidebar width based on actual text rendering requirements
  const calculateOptimalSidebarWidth = () => {
    if (!currentModule) {
      return 25; // Default fallback
    }

    const allTexts: string[] = [];

    // Add challenge titles
    currentModule.challenges.forEach((challenge) => {
      if (challenge.name) allTexts.push(challenge.name);
    });

    // Add learning material titles
    if (currentModule.resources) {
      currentModule.resources.forEach((resource) => {
        if (resource.name) allTexts.push(resource.name);
      });
    }

    // Add module name and dojo name
    if (currentModule.name) allTexts.push(currentModule.name);
    if (dojo.name) allTexts.push(dojo.name);

    // If no texts found, use default
    if (allTexts.length === 0) {
      return 25;
    }

    // Find the longest text
    const longestText = allTexts.reduce((a, b) =>
      a.length > b.length ? a : b,
    );

    // Measure actual text width using cached Canvas (optimal performance)
    const measureTextWidth = (text: string): number => {
      const context = getTextMeasureCanvas();
      if (context) {
        return Math.ceil(context.measureText(text).width) + 2; // +2px safety margin
      } else {
        // Fallback to character estimation if Canvas fails
        return text.length * 8.5; // Approximate Inter font width
      }
    };

    const textWidth = measureTextWidth(longestText);

    // Account for UI components around the text
    const padding = 48; // px-6 = 24px each side
    const margins = 24; // gaps and spacing
    const iconsBadges = 60; // info badges and icons
    const controls = 84; // header control buttons

    const totalRequiredWidth =
      textWidth + padding + margins + iconsBadges + controls;

    // Convert to percentage of screen width (assuming 1920px base)
    const screenWidth = window?.innerWidth || 1920;
    const requiredPercentage = (totalRequiredWidth / screenWidth) * 100;

    // Apply limits: minimum 20%, maximum 50%
    const calculatedWidth = Math.min(Math.max(requiredPercentage, 20), 50);

    return Math.round(calculatedWidth * 10) / 10; // Round to 1 decimal
  };

  const optimalSidebarWidth = calculateOptimalSidebarWidth();

  return (
    <ResourceTabContext.Provider
      value={{ activeResourceTab, setActiveResourceTab }}
    >
      <div className="h-screen">
        {/* Fullscreen hover handles */}
        {isFullScreen && (
          <FullscreenHoverHandles>
            {{
              header: (
                <AnimatedWorkspaceHeader
                  dojoName={dojo.name}
                  moduleName={currentModule?.name || "Module"}
                  workspaceActive={workspaceData?.active || storedActiveChallenge?.isStarting}
                  activeResource={resource}
                  onClose={onChallengeClose}
                  onResourceClose={() => {
                    if (onResourceSelect) {
                      onResourceSelect(null);
                    }
                  }}
                />
              ),
              sidebar: (
                <WorkspaceSidebar
                  module={currentModule}
                  dojoName={dojo.name}
                  activeResource={resource?.id}
                  onChallengeStart={handleChallengeStart}
                  onChallengeClose={onChallengeClose}
                  onResourceSelect={onResourceSelect}
                  isPending={startChallengeMutation.isPending}
                />
              )
            }}
          </FullscreenHoverHandles>
        )}

        <ResizablePanelGroup direction="horizontal" className="h-full">
          {/* Sidebar Panel */}
          <ResizablePanel
            defaultSize={sidebarCollapsed ? 3 : optimalSidebarWidth}
            minSize={3}
            maxSize={50}
            className={`${sidebarCollapsed ? "max-w-[48px]" : "min-w-[200px]"} ${isFullScreen ? "hidden" : ""}`}
            onResize={(size) => {
              // Only handle collapse state changes, not width updates during drag
              if (sidebarCollapsed && size > 10) {
                setSidebarCollapsed(false);
              } else if (!sidebarCollapsed && size <= 3) {
                setSidebarCollapsed(true);
              }
            }}
          >
            <WorkspaceSidebar
              module={currentModule}
              dojoName={dojo.name}
              activeResource={resource?.id}
              onChallengeStart={handleChallengeStart}
              onChallengeClose={onChallengeClose}
              onResourceSelect={onResourceSelect}
              isPending={startChallengeMutation.isPending}
            />
          </ResizablePanel>

          <ResizableHandle
            withHandle
            onDoubleClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            onMouseDown={() => {
              // Use RAF to batch state updates
              requestAnimationFrame(() => {
                setIsResizing(true);
              });

              // Listen for mouse up to end resizing
              const handleMouseUp = () => {
                requestAnimationFrame(() => {
                  setIsResizing(false);
                });
                document.removeEventListener('mouseup', handleMouseUp);
              };
              document.addEventListener('mouseup', handleMouseUp);
            }}
            className={isFullScreen ? "hidden" : ""}
          />

          {/* Main Workspace Panel */}
          <ResizablePanel
            defaultSize={
              isFullScreen
                ? 100
                : sidebarCollapsed
                  ? 97
                  : 100 - optimalSidebarWidth
            }
          >
            <div className="flex flex-col h-full bg-background">
              {/* Unified animated header for both challenges and resources */}
              <div className={isFullScreen ? "hidden" : ""}>
                <AnimatedWorkspaceHeader
                  dojoName={dojo.name}
                  moduleName={currentModule?.name || "Module"}
                  workspaceActive={workspaceData?.active || storedActiveChallenge?.isStarting}
                  activeResource={resource}
                  onClose={onChallengeClose}
                  onResourceClose={() => {
                    if (onResourceSelect) {
                      onResourceSelect(null);
                    }
                  }}
                />
              </div>

              <WorkspaceContent
                workspaceActive={workspaceData?.active || false}
                workspaceData={workspaceData}
                activeResource={resource}
                onResourceClose={() => {
                  if (onResourceSelect) {
                    onResourceSelect(null);
                  }
                }}
              />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>

        {/* Command Palette */}
        <CommandPalette
          isOpen={commandPaletteOpen}
          onClose={() => setCommandPaletteOpen(false)}
          commands={commands}
        />
      </div>
    </ResourceTabContext.Provider>
  );
}
