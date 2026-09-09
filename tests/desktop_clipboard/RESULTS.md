# Local validation, 2026-09-09

## Built artifact

Built the exact noVNC derivation selected by `workspace/services/desktop.nix`
against locked Nixpkgs `b18a4b905f8d028dc4476412e6d6891728695379`.
Upstream source is `acca57b997f206683d27796829ee1f72da37002a`.
The source hash, inherited Nixpkgs patch, gesture patch, and Dojo reconnect
patch all applied successfully.

Output: `/nix/store/4h49zisx1k97pjxwvq4yjxj9ypbc0mxh-novnc-unstable-2026-09-07`.
These built web assets were used for the final integration checks, not merely
the source checkout. Full Dojo desktop closure/deployment was not built or run.

## Results

| Browser | Real clipboard / GUI checks | noVNC unit suite |
| --- | --- | --- |
| Firefox 155.0.1 | 17 passed | 661 passed, 4 skipped |
| Chrome 153.0.8010.36, pre-granted clipboard permissions | 19 passed | 661 passed, 4 skipped |
| Chrome 153.0.8010.36, fresh profile without grants | 17 passed | Same Chrome unit run |

ESLint passed for modified JavaScript source and tests. Unit runs used Node
24.20.0 in the isolated container. Unit tests stub browser APIs; the separate
integration checks do not. Chrome pre-grants used CDP rather than manual prompt
interaction.

Real integration checks cover Unicode/multiline Ctrl+V and Ctrl+Shift+V insertion,
remote application Copy, focus and modifier restoration, idle remote-copy retry,
stale clipboard cancellation, preserved granted-Chrome focus reads, manual
recovery, and view-only gating. See README for the detailed method.

Early exploratory runs exposed and corrected Firefox's need for an editable
paste target, fresh Chromium's idle-write permission prompt stealing focus,
and Chromium mouse-capture changing the click target. Test harness fixes included
Tk's nonstandard default Ctrl+A binding, cursor-aware insertion expectations,
and importing UI in the page realm instead of Firefox's WebDriver sandbox.

## Limitations and remaining review

- Safari/macOS and mobile browsers were not run. The patch accounts for
  Command+V in unit tests; that is not a real Safari compatibility test.
- No image/rich-text clipboard support, remote application menu paste guarantee,
  mobile paste-callout coverage, or WAN ordering/latency guarantee.
- Pending remote copies are canceled on blur or local paste to avoid stale
  overwrites. A later click while staying inside the desktop can still replace
  the local clipboard; controls/messaging for that behavior need review.
- The manual panel is intentionally retained. Automatic focus reads require a
  pre-existing read grant; fresh Chromium uses explicit paste instead of a focus
  permission prompt. This differs from upstream's current UX.
- This fallback remains a draft, separate from the upstream-only version bump.

Raw JSON from this run is retained locally under
`/tmp/dojo-xpra-browser-tests.MB0fD0/results/fallback-*.json`.
