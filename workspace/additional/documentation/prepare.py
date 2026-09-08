import concurrent.futures
import html
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


def initialize_worker(root, sources):
    global PAGE_CONTEXT
    PAGE_CONTEXT = (root, sources)


def prepare_worker(page):
    prepare_page(page, *PAGE_CONTEXT)


def relative_link(destination, current, fragment="", query=""):
    return urlunsplit(
        ("", "", os.path.relpath(destination, current.parent), query, fragment)
    )


def rewrite_link(value, current, collection, root, sources):
    parsed = urlsplit(value)
    if not value or value.startswith("#") or parsed.scheme in ("mailto", "data"):
        return value
    if parsed.scheme and parsed.scheme not in ("http", "https", "file"):
        return value
    if not parsed.netloc and not parsed.scheme and not parsed.path.startswith("/"):
        local = (current.parent / unquote(parsed.path)).resolve()
        if local.is_file():
            return value
        if local.is_dir() and (local / "index.html").is_file():
            return relative_link(
                local / "index.html", current, parsed.fragment, parsed.query
            )
    source = sources[collection]
    source_root = root / collection / source.get("prefix", "")
    relative = (
        current.relative_to(source_root)
        if current.is_relative_to(source_root)
        else Path("index.html")
    )
    absolute = urlsplit(urljoin(urljoin(source["url"], relative.as_posix()), value))
    for name, source in sources.items():
        base = urlsplit(source["url"])
        if absolute.netloc.removeprefix("www.") != base.netloc.removeprefix("www."):
            continue
        path = unquote(absolute.path)
        if name == "python" and path.startswith("/3/"):
            path = base.path + path[3:]
        if not path.startswith(base.path):
            continue
        target = (
            root / name / source.get("prefix", "") / path[len(base.path) :].rstrip("/")
        )
        for destination in (target, Path(str(target) + ".html"), target / "index.html"):
            if destination.is_file():
                return relative_link(
                    destination, current, absolute.fragment, absolute.query
                )
    return urlunsplit(absolute)


def prepare_page(page, root, sources):
    collection = page.relative_to(root).parts[0]
    soup = BeautifulSoup(page.read_bytes(), "lxml")
    for tag in soup.find_all(["base", "iframe", "object", "embed"]):
        if tag.name != "base":
            notice = soup.new_tag("p")
            notice.string = "Embedded interactive content is unavailable in this offline copy; see the accompanying source examples."
            tag.replace_with(notice)
        else:
            tag.decompose()
    for tag in soup.find_all(True):
        if tag.attrs is None:
            continue
        for attribute in ("href", "src", "action", "poster"):
            if tag.get(attribute):
                tag[attribute] = rewrite_link(
                    tag[attribute], page, collection, root, sources
                )
        if tag.name == "a" and urlsplit(tag.get("href", "")).netloc:
            tag["title"] = "External website (requires network access)"
            tag.append(" [external]")
        if tag.name in ("script", "img", "link", "source", "video", "audio"):
            address = tag.get("src", tag.get("href", ""))
            if urlsplit(address).netloc:
                if tag.name == "img":
                    tag.replace_with("[External image: " + tag.get("alt", "") + "]")
                else:
                    tag.decompose()
                continue
        tag.attrs.pop("srcset", None)
    if soup.head:
        policy = soup.new_tag("meta")
        policy["http-equiv"] = "Content-Security-Policy"
        policy["content"] = (
            "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'none'; "
            "form-action 'self' file:; base-uri 'none'"
        )
        soup.head.insert(0, policy)
    page.write_text(str(soup))
    body = soup.find("main") or soup.find("div", class_="body") or soup.body or soup
    for tag in body.find_all(["script", "style", "nav", "footer"]):
        tag.decompose()
    result = subprocess.run(
        [
            "w3m",
            "-dump",
            "-T",
            "text/html",
            "-cols",
            "100",
            "-I",
            "UTF-8",
            "-O",
            "UTF-8",
        ],
        input=str(body),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    text_path = root / "text" / page.relative_to(root).with_suffix(".txt")
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(result.stdout)


def main(sources_path, output):
    sources = json.loads(Path(sources_path).read_text())
    root = Path(output)
    root.mkdir(parents=True)
    for name, source in sources.items():
        destination = root / name
        shutil.copytree(
            source["path"],
            destination,
            copy_function=shutil.copyfile,
            ignore=shutil.ignore_patterns(".doctrees"),
        )
        for directory in [
            destination,
            *(p for p in destination.rglob("*") if p.is_dir()),
        ]:
            directory.chmod(0o755)
        if source.get("license"):
            shutil.copyfile(source["license"], root / name / "LICENSE")
    pages = sorted(root.rglob("*.html"))
    workers = min(8, max(1, int(os.environ.get("NIX_BUILD_CORES", "1"))))
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers,
        initializer=initialize_worker,
        initargs=(root, sources),
    ) as executor:
        for count, _ in enumerate(executor.map(prepare_worker, pages, chunksize=32), 1):
            if count % 2000 == 0:
                print(f"Prepared {count:,}/{len(pages):,} pages", flush=True)
    metadata = {
        name: {key: value for key, value in source.items() if key in ("version", "url")}
        for name, source in sources.items()
    }
    (root / "sources.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    )
    entries = "".join(
        f'<li><a href="{name}/index.html">{name}</a> ({html.escape(source["version"])})</li>'
        for name, source in sources.items()
    )
    (root / "index.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Offline documentation</title></head><body>'
        "<h1>Offline documentation</h1><ul>" + entries + "</ul>"
        "<p>Read with w3m or the workspace browser. Links marked [external] require network access.</p>"
        '<p>Search the text copies from the terminal:</p><pre>rg -n -i "URLSearchParams" /run/dojo/share/doc/text/mdn</pre>'
        "<p>In w3m: Tab selects the next link, Enter follows it, B goes back, / searches this page, q quits.</p>"
        "<p>Interactive web examples are not executed in this offline collection.</p>"
        "</body></html>"
    )
    print(f"Prepared {len(pages):,} HTML pages and matching searchable text files")


if __name__ == "__main__":
    main(*sys.argv[1:])
