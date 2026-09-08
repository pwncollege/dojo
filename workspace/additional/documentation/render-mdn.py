import html
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path


def link(url, title):
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(title)}</a>'


def compatibility(data, query):
    node = data
    for part in query.split("."):
        node = node.get(part, {})
    if not node:
        return "<p>No browser compatibility data is recorded for this entry.</p>"
    return (
        "<pre>" + html.escape(json.dumps(node, indent=2, ensure_ascii=False)) + "</pre>"
    )


def render_sections(sections, browser_data):
    result = []
    for section in sections:
        value = section["value"]
        heading = "h3" if value.get("isH3") else "h2"
        if value.get("title"):
            result.append(
                f'<{heading} id="{html.escape(value.get("id") or "", quote=True)}">'
                f"{value['title']}</{heading}>"
            )
        result.append(value.get("content") or "")
        if section["type"] == "browser_compatibility":
            for query in value["query"].split(","):
                result.append(compatibility(browser_data, query.strip()))
        elif section["type"] == "specifications":
            result.append(
                "<ul>"
                + "".join(
                    "<li>" + link(spec["bcdSpecificationURL"], spec["title"]) + "</li>"
                    for spec in value["specifications"]
                )
                + "</ul>"
            )
        elif section["type"] != "prose":
            raise ValueError(f"Unknown MDN section type: {section['type']}")
    return "\n".join(result)


def document(title, body):
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>"
        "<style>body{max-width:80rem;margin:2rem auto;padding:0 1rem;line-height:1.5;"
        "font-family:system-ui,sans-serif}pre{overflow:auto;padding:1rem;background:#f3f3f3}"
        "table{border-collapse:collapse}td,th{padding:.4rem;border:1px solid #aaa}"
        "img{max-width:100%}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>{body}</body></html>"
    )


def main(rendered, source, browser_data_path, output):
    rendered, source, output = map(Path, (rendered, source, output))
    browser_data = json.loads(Path(browser_data_path).read_text())
    issue_counts = Counter()
    metadata_gaps = defaultdict(list)
    for issues in json.loads((output / "issues.json").read_text()).values():
        for issue in issues:
            fields = dict(issue["fields"])
            kind = fields.get("source", "informational")
            issue_counts[kind] += 1
            if kind == "templ-mdn-data-missing":
                slug = dict(issue["spans"])["slug"]
                metadata_gaps["/en-US/docs/" + slug].append(fields["name"])
            elif kind.startswith("templ-") and kind not in (
                "templ-redirected-link",
                "templ-broken-link",
            ):
                raise ValueError(f"MDN template failed: {fields}")
    target = output / "html"
    target.mkdir(parents=True)
    pages = sorted(rendered.glob("en-us/docs/**/index.json"))
    expected = len(list((source / "files/en-us").rglob("index.md")))
    if len(pages) != expected:
        raise ValueError(
            f"MDN build produced {len(pages)} pages for {expected} source pages"
        )
    entries = []
    urls = {}
    for page in pages:
        doc = json.loads(page.read_text())["doc"]
        destination = target / page.relative_to(rendered).with_suffix(".html")
        destination.parent.mkdir(parents=True, exist_ok=True)
        urls[doc["mdn_url"].lower()] = str(destination.relative_to(target))
        for asset in page.parent.iterdir():
            if asset.is_file() and asset.suffix not in (".json", ".md"):
                shutil.copyfile(asset, destination.parent / asset.name)
        body = "<nav>" + link("/index.html", "MDN offline index") + " | "
        body += " / ".join(
            link(parent["uri"], parent["title"]) for parent in doc.get("parents", [])
        )
        body += "</nav><main>"
        for gap in metadata_gaps.get(doc["mdn_url"], []):
            body += (
                "<aside><p>Upstream metadata is not yet available for "
                + html.escape(gap)
            )
            body += ". The article is included, but its generated metadata is incomplete.</p></aside>"
        body += render_sections(doc.get("body", []), browser_data) + "</main>"
        body += "<footer><p>MDN contributors. Offline rendering of "
        body += link("https://developer.mozilla.org" + doc["mdn_url"], doc["title"])
        body += ". " + link(
            doc["source"]["github_url"], "Source and contributor history"
        )
        body += ". See the bundled MDN license for attribution and reuse terms.</p></footer>"
        destination.write_text(document(doc["title"], body))
        entries.append((doc["title"], doc["mdn_url"]))
    entries.sort(key=lambda entry: (entry[0].casefold(), entry[1]))
    categories = [
        "Web",
        "Web/HTTP",
        "Web/HTML",
        "Web/CSS",
        "Web/JavaScript",
        "Web/API",
        "Learn_web_development",
        "Glossary",
    ]
    body = "<p>English MDN documentation, rendered for offline reading. External services and live examples require the web.</p><ul>"
    body += "".join(
        "<li>" + link("/en-US/docs/" + category, category) + "</li>"
        for category in categories
    )
    body += (
        "</ul><p>"
        + link("all.html", f"All {len(entries):,} documentation pages (alphabetical)")
        + "</p>"
    )
    body += (
        "<p>"
        + link("build-notes.html", "Snapshot limitations and build notes")
        + "</p>"
    )
    (target / "index.html").write_text(document("MDN offline documentation", body))
    (target / "all.html").write_text(
        document(
            "MDN alphabetical index",
            "<ul>"
            + "".join("<li>" + link(url, title) + "</li>" for title, url in entries)
            + "</ul>",
        )
    )
    notes = "<p>Every English article in the pinned snapshot is included. Links to pages outside the snapshot remain external.</p>"
    notes += "<p>Some newer CSS features do not yet have metadata in the upstream dataset. Affected articles are marked:</p><ul>"
    notes += "".join(
        "<li>" + link(url, "; ".join(gaps)) + "</li>"
        for url, gaps in sorted(metadata_gaps.items())
    )
    notes += (
        "</ul><p>Renderer diagnostics:</p><pre>"
        + html.escape(json.dumps(dict(sorted(issue_counts.items())), indent=2))
        + "</pre>"
    )
    (target / "build-notes.html").write_text(
        document("MDN snapshot build notes", notes)
    )
    shutil.copyfile(source / "LICENSE.md", output / "LICENSE.md")
    shutil.copyfile(source / "files/en-us/_redirects.txt", output / "redirects.txt")
    (output / "urls.json").write_text(json.dumps(urls, sort_keys=True))
    print(f"Rendered all {len(pages):,} English MDN pages")


if __name__ == "__main__":
    main(*sys.argv[1:])
