import json
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from lxml import html as html_tree

from prepare import relative_link, resolve_mdn, rewrite_link


ROOT = Path(sys.argv.pop(1))


class DocumentationTests(unittest.TestCase):
    def test_collections(self):
        for name in ("python", "sqlite", "requests", "flask", "mdn"):
            with self.subTest(name=name):
                self.assertTrue((ROOT / name / "index.html").is_file())
                self.assertTrue((ROOT / "text" / name / "index.txt").is_file())
        metadata = json.loads((ROOT / "sources.json").read_text())
        self.assertEqual(len(metadata), 5)

    def test_reference_content(self):
        examples = {
            "python/library/base64.txt": "b64decode",
            "python/library/stdtypes.txt": "fromhex",
            "python/library/urllib.parse.txt": "urlencode",
            "python/library/sqlite3.txt": "execute",
            "sqlite/lang_corefunc.txt": "substr",
            "sqlite/schematab.txt": "sqlite_schema",
            "requests/user/quickstart.txt": "cookies",
            "flask/quickstart.txt": "request",
            "mdn/en-us/docs/web/api/urlsearchparams/index.txt": "URLSearchParams",
            "mdn/en-us/docs/web/api/fetch_api/using_fetch/index.txt": "fetch",
        }
        for path, expected in examples.items():
            with self.subTest(path=path):
                self.assertIn(expected, (ROOT / "text" / path).read_text())

    def test_every_html_page_has_text_and_no_broken_local_links(self):
        broken = []
        pages = list(ROOT.glob("*/*.html")) + [
            page
            for name in ("python", "sqlite", "requests", "flask", "mdn")
            for page in (ROOT / name).rglob("*.html")
            if page.parent != ROOT / name
        ]
        for page in pages:
            self.assertTrue(
                (ROOT / "text" / page.relative_to(ROOT).with_suffix(".txt")).is_file()
            )
            tree = html_tree.fromstring(page.read_bytes())
            for tag in tree.xpath("//a[@href]"):
                value = urlsplit(tag.get("href"))
                if value.scheme or value.netloc or not value.path:
                    continue
                destination = page.parent / unquote(value.path)
                if not destination.is_file():
                    broken.append(f"{page.relative_to(ROOT)} -> {tag.get('href')}")
        self.assertEqual(broken[:20], [], f"{len(broken)} broken local links")

    def test_python_tutorial_link(self):
        page = ROOT / "python/index.html"
        soup = BeautifulSoup(page.read_bytes(), "lxml")
        tutorial = soup.find("a", href="tutorial/index.html")
        self.assertIsNotNone(tutorial)
        destination = page.parent / tutorial["href"]
        result = subprocess.run(
            ["w3m", "-dump", str(destination)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("The Python Tutorial", result.stdout)

    def test_mdn_cross_reference(self):
        page = ROOT / "mdn/en-us/docs/web/api/urlsearchparams/index.html"
        soup = BeautifulSoup(page.read_bytes(), "lxml")
        links = [tag["href"] for tag in soup.find_all("a", href=True)]
        self.assertIn("append/index.html", links)

    def test_redirects_and_case(self):
        destination = resolve_mdn(
            "/en-US/docs/Old",
            ROOT / "mdn",
            {"/en-us/docs/new": "new/index.html"},
            {"/en-us/docs/old": "/en-us/docs/new"},
        )
        self.assertEqual(destination, ROOT / "mdn/new/index.html")
        self.assertIsNone(resolve_mdn("/loop", ROOT, {}, {"/loop": "/loop"}))

    def test_relative_fragment_and_query(self):
        self.assertEqual(
            relative_link(
                ROOT / "python/library/base64.html",
                ROOT / "python/index.html",
                "base64.b64decode",
                "q=test",
            ),
            "library/base64.html?q=test#base64.b64decode",
        )

    def test_absolute_python_link_becomes_local(self):
        sources = {"python": {"url": "https://docs.python.org/3.13/"}}
        self.assertEqual(
            rewrite_link(
                "https://docs.python.org/3/library/base64.html#base64.b64decode",
                ROOT / "python/index.html",
                "python",
                ROOT,
                sources,
                {},
                {},
            ),
            "library/base64.html#base64.b64decode",
        )


if __name__ == "__main__":
    unittest.main()
