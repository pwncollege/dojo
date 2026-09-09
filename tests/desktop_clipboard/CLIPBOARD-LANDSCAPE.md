# noVNC clipboard landscape (2026-09-09)

Reviewed GitHub issue/PR search, PR bodies, discussions, relevant diffs, and browser documentation. Older browser observations are historical, not current compatibility guarantees.

## Most relevant upstream work

- [#1993](https://github.com/novnc/noVNC/pull/1993), merged: intentionally permission-based automatic synchronization for Chromium. Firefox/WebKit were excluded because async reads prompt and the permission model differs. Maintainer samhed explicitly described a Firefox/Safari follow-up as desirable. Its browser matrix included iOS Chrome/Edge/Firefox, all taking the WebKit path in those tests. Browser branding alone is not a sound capability test.
- [#1511](https://github.com/novnc/noVNC/issues/1511), still open: original request includes an opt-out and direction controls. Maintainer's latest relevant comment says Chromium is fixed on master, Firefox/Safari still need work.
- [#2020](https://github.com/novnc/noVNC/pull/2020), open, and [#2066](https://github.com/novnc/noVNC/pull/2066), open: restore manual clipboard when browser access is denied. Both are narrow UI changes, not cross-browser gesture synchronization. Discussion distinguishes permission to automatically read the host clipboard from a user's explicit manual paste. Authors point out privacy risks when focus automatically sends unrelated sensitive clipboard contents to another remote session. Maintainers debate whether manual fallback is confusing after denial; one suggests a notification explaining fallback.
- [#1347](https://github.com/novnc/noVNC/pull/1347), closed: early clipboard module proposal. Maintainers already identified the conflict between noVNC preventing Ctrl+V and relying on native paste events. Closed after #1993, not proof that Firefox/Safari work.
- [#1562](https://github.com/novnc/noVNC/pull/1562), closed: continuation with passing unit tests on major browsers, but actual behavior remained unresolved. Users reported that fresh local text was not transferred and stale remote text was pasted. Closed after author inactivity, rather than because gestures were rejected in principle.
- [#1817](https://github.com/novnc/noVNC/pull/1817), closed: continuation fixing paste behavior and trying execCommand for broader compatibility. Relevant precedent, but not a current drop-in patch against the new clipboard module.
- [#509](https://github.com/novnc/noVNC/issues/509): a historical comment demonstrates hidden-field paste capture, delaying forwarded paste keys, and execCommand copy from a user gesture. This is close to the approach we are testing, but its stated Chrome/Firefox versions are old.
- [#1931](https://github.com/novnc/noVNC/issues/1931), open: mask sensitive text in the manual clipboard field. Another reminder that the panel itself can expose sensitive clipboard contents on screen.

## Implications for the local fallback

1. Keep Chromium's already-granted focus synchronization, but do not automatically prompt on every focus. A real paste event can transfer local text without a persistent read grant. This is a deliberate UX change from upstream for fresh Chromium profiles.
2. Forward text before the remote paste chord and test actual GUI insertion with stale remote text preloaded. Unit tests alone are insufficient evidence.
3. Attempt remote writes when focused, queue denied writes for a desktop gesture, cancel stale queues on blur or local paste, and preserve manual recovery. No background reads on Firefox/Safari.
4. Native paste capture needs an editable target in Firefox; noVNC's ordinary canvas keyboard handler suppresses browser paste. We use a hidden textarea only while handling a paste shortcut and restore canvas focus.
5. The desktop click retry can overwrite the local clipboard during a later, otherwise unrelated desktop interaction. It is not permission to continuously read the clipboard, but still needs understandable UI and a privacy/control decision before broad rollout.
6. Do not market this as complete browser-independent automatic sync. Safari/macOS, mobile soft-keyboard/callout paste, application menu paste, rich text/images, and long-latency paste ordering still need separate coverage.

Browser references: [MDN Clipboard API](https://developer.mozilla.org/en-US/docs/Web/API/Clipboard_API#security_considerations), [WebKit's Clipboard API design](https://webkit.org/blog/10855/async-clipboard-api/). WebKit explicitly requires gesture-bound writes and describes native paste gestures as authorization for reads; this supports the direction of the design but does not validate our focus/keyboard implementation on Safari.

## Reconnect patch

Keep the existing reconnect patch in the upgrade. [Dojo #463](https://github.com/pwncollege/dojo/pull/463) added it to stop endless rapid retry attempts introduced by [noVNC #1672](https://github.com/novnc/noVNC/pull/1672). Current upstream still has the unconditional retry branch after unclean errors, and Dojo still uses reconnect_delay=200 ms. The patch makes it an else-if: clean disconnects can reconnect, unclean failures stop. Bounded retries/backoff would be a separate behavior change, not removal of obsolete packaging debris.
