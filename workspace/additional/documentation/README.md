# Offline workspace documentation

The full workspace includes `w3m` and five documentation collections. The core
workspace is unchanged. No per-challenge image changes, documentation server, or
home-directory initialization are required.

## Reading and searching

```sh
w3m /run/dojo/share/doc/index.html
w3m /run/dojo/share/doc/python/index.html
w3m /run/dojo/share/doc/sqlite/index.html
w3m /run/dojo/share/doc/requests/index.html
w3m /run/dojo/share/doc/flask/index.html
w3m /run/dojo/share/doc/mdn/index.html

rg -l -i 'URLSearchParams' /run/dojo/share/doc/text/mdn
rg -n -F 'bytes.fromhex' /run/dojo/share/doc/text/python | less
less /run/dojo/share/doc/text/python/library/base64.txt
```

In `w3m`, Tab selects the next link, Enter follows it, capital B goes back, `/`
searches the current page, and `q` quits. Mouse navigation depends on the terminal.
The full-text search commands search the entire selected collection, not just the
current page. The Python documentation's module index is also useful for locating
specific APIs.

The same HTML can be opened in Firefox from the workspace desktop:

```sh
firefox /run/dojo/share/doc/index.html
```

Links to included pages are rewritten to relative local paths. External links are
marked `[external]` and require network access. Remote embedded resources are
removed and a content security policy blocks background network requests.
Interactive MDN embeds are replaced with a
notice; the accompanying source examples remain. The collection is documentation,
not an offline implementation of MDN's web services.

## Sources and build

Python and SQLite use the `python3.doc` and `sqlite.doc` packages from the workspace's
pinned Nixpkgs. Requests and Flask build the documentation in their packaged source
releases with Sphinx, using the installed package for API extraction. Intersphinx
network fetches are disabled; the standard Alabaster theme avoids online theme
integrations. Copyright/license material is retained.

MDN includes every English article in the pinned `mdn/content` snapshot in
`mdn.nix`. Rari expands upstream macros, navigation references, CSS syntax and
specifications. `render-mdn.py` presents that rendered content as static HTML,
including browser compatibility data as searchable JSON. The build checks that
every source article produced a page. MDN's license and per-page source attribution
are retained. The alphabetical index lists the complete collection.

The MDN index links to snapshot build notes. Articles whose experimental CSS
metadata is missing from upstream's dataset carry an explicit notice; their prose
is still included. Redirects are resolved locally when their target is packaged.

`mdn-dependencies.json` pins the supporting datasets by version and integrity hash.
The small Rari build patch reads those already-fetched packages instead of checking
the npm registry, and skips popularity rankings and developer-interest signals.
Those are not needed to read the article corpus. The web-extension example catalog
is fetched from a separately pinned source commit. The renderer's declared Rust
minimum is newer than the workspace compiler;
the package explicitly ignores that version gate, with compilation and the document
build providing the compatibility check.

The final assembly generates plain-text copies using `w3m`, writes `sources.json`
with versions and upstream URLs, and runs content/link checks. The installed output
contains documentation, not the MDN renderer or its build toolchain.

Build the documentation without rebuilding the entire full workspace:

```sh
nix build path:./workspace#documentation --no-update-lock-file
```

The full workspace already includes this output through `tools.documentation` in
`additional.nix`. Building does not deploy it; the normal workspace-builder rollout
is still required. Once deployed, verify both keyboard and mouse navigation in
the embedded terminal and local HTML navigation in the workspace desktop, including
a fresh home directory.

To update MDN, update its source revision/hash and the dataset pins together, then
rebuild and run the embedded checks. Python, SQLite, Requests, and Flask follow the
workspace's Nixpkgs pin automatically.
