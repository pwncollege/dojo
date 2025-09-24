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
  terminalToJson = theme: pkgs.writeText "terminal-theme.json" (builtins.toJSON theme.terminal);

  # Helper function to convert VS Code colors to JSON with proper theme selection
  vscodeToJson = themeName: theme: pkgs.writeText "vscode-theme.json" (builtins.toJSON (
    let
      baseSettings = {
        "window.autoDetectColorScheme" = false;
        "window.commandCenter" = false;
        "workbench.layoutControl.enabled" = false;
        "editor.fontFamily" = "JetBrainsMono Nerd Font, DejaVu Sans Mono, Consolas, Monaco, Menlo, Courier New, monospace";
        "editor.fontSize" = 14;
        "editor.fontLigatures" = true;
        "terminal.integrated.fontFamily" = "JetBrainsMono Nerd Font, DejaVu Sans Mono, Consolas, Monaco, Menlo, Courier New, monospace";
        "terminal.integrated.fontSize" = 14;
         "editor.minimap.enabled" = false;
      };
    in
    if themeName == "gruvbox" then
      baseSettings // {
        "workbench.colorTheme" = "Gruvbox Crisp (High Contrast, with TeX)";
      }
    else if themeName == "everforest" then
      baseSettings // {
        "workbench.colorTheme" = "Everforest Dark";
      }
    else if themeName == "matrix" then
      baseSettings // {
        "workbench.colorTheme" = "Matrixish";
      }
    else if themeName == "solarized" then
      baseSettings // {
        "workbench.colorTheme" = "Solarized Dark";
      }
    else if themeName == "perplexity" then
      baseSettings // {
        "workbench.colorTheme" = "Default Dark+";
      }
    else # amethyst and any other themes use default
      baseSettings // {
        "workbench.colorTheme" = "Default Dark+";
      }
  ));

  # Available themes
  themes = {
    inherit matrix everforest gruvbox amethyst solarized perplexity;
  };

  # Function to get theme by name with fallback
  getTheme = name: themes.${name} or themes.matrix;

in {
  inherit themes getTheme terminalToJson vscodeToJson;

  # Export specific functions for services
  getTerminalTheme = name: terminalToJson (getTheme name);
  getVSCodeTheme = name: vscodeToJson name (getTheme name);
}
