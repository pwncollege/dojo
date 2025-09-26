{ pkgs }:

let
  # Import all theme files
  matrix = import ./matrix.nix;
  everforest = import ./everforest.nix;
  gruvbox = import ./gruvbox.nix;
  amethyst = import ./amethyst.nix;
  solarized = import ./solarized.nix;
  perplexity = import ./perplexity.nix;

  # Helper function to convert terminal colors to JSON
  terminalToJson = theme:
    pkgs.writeText "terminal-theme.json" (builtins.toJSON theme.terminal);

  # Helper function to convert VS Code colors to JSON with proper theme selection
  vscodeToJson = themeName: theme:
    pkgs.writeText "vscode-theme.json" (builtins.toJSON (let
      baseSettings = {
        "window.autoDetectColorScheme" = false;
        "window.commandCenter" = false;
        "workbench.layoutControl.enabled" = false;
        "editor.fontFamily" =
          "JetBrainsMono Nerd Font, DejaVu Sans Mono, Consolas, Monaco, Menlo, Courier New, monospace";
        "editor.fontSize" = 14;
        "editor.fontLigatures" = true;
        "terminal.integrated.fontFamily" =
          "JetBrainsMono Nerd Font, DejaVu Sans Mono, Consolas, Monaco, Menlo, Courier New, monospace";
        "terminal.integrated.fontSize" = 14;
        "editor.minimap.enabled" = false;
        "workbench.iconTheme" = "material-icon-theme";

      };
    in if themeName == "gruvbox" then
      baseSettings // {
        "workbench.colorTheme" = "Gruvbox Crisp (High Contrast, with TeX)";
      }
    else if themeName == "everforest" then
      baseSettings // { "workbench.colorTheme" = "Everforest Dark"; }
    else if themeName == "matrix" then
      baseSettings // { "workbench.colorTheme" = "Matrixish"; }
    else if themeName == "solarized" then
      baseSettings // { "workbench.colorTheme" = "Solarized Dark"; }
    else if themeName == "perplexity" then
      baseSettings // {
        "workbench.colorTheme" = "Everblush";
        "workbench.colorCustomizations" = {
          # Editor colors - Using authentic Perplexity theme colors
          "editor.background" = "#0a1a20";
          "editor.foreground" = "#4de8e8";
          "editorLineNumber.foreground" = "#36a5a5";
          "editorLineNumber.activeForeground" = "#4de8e8";
          "editor.selectionBackground" = "#164955";
          "editor.selectionHighlightBackground" = "#16495533";
          "editor.lineHighlightBackground" = "#0c2025";
          "editorCursor.foreground" = "#4de8e8";
          "editorIndentGuide.background" = "#164955";
          "editorIndentGuide.activeBackground" = "#36a5a5";

          # Sidebar
          "sideBar.background" = "#0c2025";
          "sideBar.foreground" = "#4de8e8";
          "sideBar.border" = "#164955";
          "sideBarTitle.foreground" = "#4de8e8";

          # Lists and trees
          "list.activeSelectionBackground" = "#164955";
          "list.activeSelectionForeground" = "#4de8e8";
          "list.hoverBackground" = "#0f3039";
          "list.hoverForeground" = "#4de8e8";
          "list.highlightForeground" = "#4de8e8";

          # Activity Bar
          "activityBar.background" = "#0c2025";
          "activityBar.foreground" = "#4de8e8";
          "activityBar.inactiveForeground" = "#36a5a5";
          "activityBar.border" = "#164955";
          "activityBar.activeBorder" = "#4de8e8";
          "activityBarBadge.background" = "#4de8e8";
          "activityBarBadge.foreground" = "#0a1a20";

          # Status Bar
          "statusBar.background" = "#0a1a20";
          "statusBar.foreground" = "#4de8e8";
          "statusBar.border" = "#164955";
          "statusBar.noFolderBackground" = "#0a1a20";
          "statusBar.debuggingBackground" = "#4de8e8";
          "statusBar.debuggingForeground" = "#0a1a20";
          "statusBarItem.hoverBackground" = "#164955";
          "statusBarItem.activeBackground" = "#0f3039";
          "statusBarItem.prominentBackground" = "#4de8e8";
          "statusBarItem.prominentForeground" = "#0a1a20";
          "statusBarItem.prominentHoverBackground" = "#36a5a5";
          "statusBarItem.remoteBackground" = "#4de8e8";
          "statusBarItem.remoteForeground" = "#0a1a20";

          # Title Bar
          "titleBar.activeBackground" = "#0a1a20";
          "titleBar.activeForeground" = "#4de8e8";
          "titleBar.inactiveBackground" = "#0c2025";
          "titleBar.inactiveForeground" = "#36a5a5";
          "titleBar.border" = "#164955";

          # Tabs
          "tab.activeBackground" = "#0a1a20";
          "tab.activeForeground" = "#4de8e8";
          "tab.activeBorder" = "#4de8e8";
          "tab.inactiveBackground" = "#0c2025";
          "tab.inactiveForeground" = "#36a5a5";
          "tab.border" = "#164955";

          # Panel
          "panel.background" = "#0a1a20";
          "panel.border" = "#164955";
          "panelTitle.activeBorder" = "#4de8e8";
          "panelTitle.activeForeground" = "#4de8e8";

          # Terminal
          "terminal.background" = "#0a1a20";
          "terminal.foreground" = "#4de8e8";

          # Input
          "input.background" = "#164955";
          "input.foreground" = "#4de8e8";
          "input.border" = "#36a5a5";

          # Button
          "button.background" = "#4de8e8";
          "button.foreground" = "#0a1a20";
          "button.hoverBackground" = "#36a5a5";

          # Git colors
          "gitDecoration.addedResourceForeground" = "#52d681";
          "gitDecoration.modifiedResourceForeground" = "#4de8e8";
          "gitDecoration.deletedResourceForeground" = "#e83c3c";

          # Error/Warning colors
          "editorError.foreground" = "#e83c3c";
          "editorWarning.foreground" = "#ffdb7d";
          "editorInfo.foreground" = "#4de8e8";
        };
      }
    else if themeName == "amethyst" then
      baseSettings // {
        "workbench.colorTheme" = "Default Dark Modern";
        "workbench.colorCustomizations" = {
          # Editor colors - Using authentic Amethyst theme colors
          "editor.background" = "#1a1622";
          "editor.foreground" = "#e6dced";
          "editorLineNumber.foreground" = "#b0a1c1";
          "editorLineNumber.activeForeground" = "#ddb4d0";
          "editor.selectionBackground" = "#332c42";
          "editor.selectionHighlightBackground" = "#332c4233";
          "editor.lineHighlightBackground" = "#231f2e";
          "editorCursor.foreground" = "#b77dd8";
          "editorIndentGuide.background" = "#332c42";
          "editorIndentGuide.activeBackground" = "#3e3350";

          # Sidebar
          "sideBar.background" = "#231f2e";
          "sideBar.foreground" = "#e6dced";
          "sideBar.border" = "#332c42";
          "sideBarTitle.foreground" = "#e6dced";

          # Lists and trees
          "list.activeSelectionBackground" = "#332c42";
          "list.activeSelectionForeground" = "#e6dced";
          "list.hoverBackground" = "#3e3350";
          "list.hoverForeground" = "#e6dced";
          "list.highlightForeground" = "#b77dd8";

          # Activity Bar
          "activityBar.background" = "#231f2e";
          "activityBar.foreground" = "#e6dced";
          "activityBar.inactiveForeground" = "#b0a1c1";
          "activityBar.border" = "#332c42";
          "activityBar.activeBorder" = "#b77dd8";
          "activityBarBadge.background" = "#b77dd8";
          "activityBarBadge.foreground" = "#1a1622";

          # Status Bar
          "statusBar.background" = "#1a1622";
          "statusBar.foreground" = "#e6dced";
          "statusBar.border" = "#332c42";
          "statusBar.noFolderBackground" = "#1a1622";
          "statusBar.debuggingBackground" = "#b77dd8";
          "statusBar.debuggingForeground" = "#1a1622";
          "statusBarItem.hoverBackground" = "#332c42";
          "statusBarItem.activeBackground" = "#3e3350";
          "statusBarItem.prominentBackground" = "#b77dd8";
          "statusBarItem.prominentForeground" = "#1a1622";
          "statusBarItem.prominentHoverBackground" = "#a89eff";
          "statusBarItem.remoteBackground" = "#b77dd8";
          "statusBarItem.remoteForeground" = "#1a1622";

          # Title Bar
          "titleBar.activeBackground" = "#1a1622";
          "titleBar.activeForeground" = "#e6dced";
          "titleBar.inactiveBackground" = "#231f2e";
          "titleBar.inactiveForeground" = "#b0a1c1";
          "titleBar.border" = "#332c42";

          # Tabs
          "tab.activeBackground" = "#1a1622";
          "tab.activeForeground" = "#e6dced";
          "tab.activeBorder" = "#b77dd8";
          "tab.inactiveBackground" = "#231f2e";
          "tab.inactiveForeground" = "#b0a1c1";
          "tab.border" = "#332c42";

          # Panel
          "panel.background" = "#1a1622";
          "panel.border" = "#332c42";
          "panelTitle.activeBorder" = "#b77dd8";
          "panelTitle.activeForeground" = "#e6dced";

          # Terminal
          "terminal.background" = "#1a1622";
          "terminal.foreground" = "#e6dced";

          # Input
          "input.background" = "#332c42";
          "input.foreground" = "#e6dced";
          "input.border" = "#b0a1c1";

          # Button
          "button.background" = "#b77dd8";
          "button.foreground" = "#1a1622";
          "button.hoverBackground" = "#a89eff";

          # Git colors
          "gitDecoration.addedResourceForeground" = "#52d681";
          "gitDecoration.modifiedResourceForeground" = "#b77dd8";
          "gitDecoration.deletedResourceForeground" = "#c95762";

          # Error/Warning colors
          "editorError.foreground" = "#e84855";
          "editorWarning.foreground" = "#ffdb7d";
          "editorInfo.foreground" = "#a89eff";
        };
      }
    else # other themes use default
      baseSettings // { "workbench.colorTheme" = "Default Dark+"; }));

  # Available themes
  themes = { inherit matrix everforest gruvbox amethyst solarized perplexity; };

  # Function to get theme by name with fallback
  getTheme = name: themes.${name} or themes.matrix;

in {
  inherit themes getTheme terminalToJson vscodeToJson;

  # Export specific functions for services
  getTerminalTheme = name: terminalToJson (getTheme name);
  getVSCodeTheme = name: vscodeToJson name (getTheme name);
}
