import json
import posixpath
from pathlib import Path
import sys
from urllib.parse import unquote, urljoin, urlsplit

from lxml import html

source, destination = map(Path, sys.argv[1:])
pages = json.loads((source / "db.json").read_text())


def filename(path):
    return path if path.endswith(".html") else path + ".html"


files = {filename(page) for page in pages}
for page, content in pages.items():
    document = html.fragment_fromstring(content, create_parent="div")
    for link in document.xpath(".//a[@href]"):
        target = urlsplit(link.get("href"))
        if target.scheme or target.netloc or not target.path:
            continue
        resolved = unquote(urljoin("/" + filename(page), target.path)).lstrip("/")
        candidate = filename(resolved)
        if candidate in files:
            relative = posixpath.relpath(
                candidate, posixpath.dirname(filename(page)) or "."
            )
            link.set("href", target._replace(path=relative).geturl())
    output = destination / filename(page)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html.tostring(document, encoding="unicode"))

index = {}
for entry in json.loads((source / "index.json").read_text())["entries"]:
    path, separator, anchor = entry["path"].partition("#")
    target = filename(path)
    assert target in files, entry
    index[entry["name"]] = target + separator + anchor
(destination / "index.json").write_text(json.dumps(index))
