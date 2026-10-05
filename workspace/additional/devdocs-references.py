import copy
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urljoin

from lxml import etree, html


def text(element):
    return " ".join(element.text_content().split())


def write_index(destination, entries):
    (destination / "index.json").write_text(json.dumps(entries, sort_keys=True))


def write_page(destination, title, content, source_url):
    for link in content.xpath(".//a[@href]"):
        target = link.get("href")
        if not target.startswith("#"):
            link.set("href", urljoin(source_url, target))
    document = html.Element("html")
    head = etree.SubElement(document, "head")
    etree.SubElement(head, "meta", charset="utf-8")
    etree.SubElement(head, "title").text = title
    body = etree.SubElement(document, "body")
    etree.SubElement(body, "h1").text = title
    body.append(content)
    source = etree.SubElement(body, "p")
    etree.SubElement(source, "a", href=source_url).text = "Source"
    destination.write_text(
        html.tostring(document, encoding="unicode"), encoding="utf-8"
    )


def import_x86(source, destination):
    shutil.copytree(source, destination)
    destination.chmod(0o755)
    index = {}
    aliases = {}
    catalog = html.parse(str(destination / "index.html"))
    links = catalog.xpath("//table//td[1]/a[@href]")
    for link in links:
        target = link.get("href")
        name = text(link).lower()
        if name not in index or Path(target).stem.lower() == name:
            index[name] = target
    for target in sorted({link.get("href") for link in links}):
        document = html.parse(str(destination / target))
        index[text(document.find(".//h1"))] = target
        columns = [text(heading) for heading in document.xpath("//table[1]//tr[1]/th")]
        if "Instruction" in columns:
            column = columns.index("Instruction") + 1
            for cell in document.xpath(f"//table[1]//tr/td[{column}]"):
                instruction = text(cell).split()
                if instruction and re.fullmatch(r"[A-Z][A-Z0-9]+", instruction[0]):
                    aliases.setdefault(instruction[0].lower(), target)
    write_index(destination, aliases | index)


def import_syscalls(source, destination):
    destination.mkdir()
    document = html.parse(str(source), parser=html.HTMLParser(encoding="utf-8"))
    table = document.find(".//table")
    headings = table.xpath(".//thead/tr/th")
    index = {}
    for row in table.xpath(".//tbody/tr"):
        cells = row.findall("td")
        name = text(cells[1])
        number = text(cells[0])
        cells[3].text = hex(int(text(cells[3]), 16))
        row.set("id", name)
        entry = html.Element("table")
        for heading, cell in zip(headings, cells, strict=True):
            field = etree.SubElement(entry, "tr")
            etree.SubElement(field, "th").text = text(heading)
            field.append(copy.deepcopy(cell))
        write_page(destination / f"{name}.html", name, entry, "https://x64.syscall.sh/")
        index[name] = f"{name}.html"
        index[f"{number} — {name}"] = f"{name}.html"
    content = html.Element("div")
    content.append(table)
    content.append(document.xpath('//div[@class="copyright"]')[0])
    write_page(
        destination / "index.html", "x64.syscall.sh", content, "https://x64.syscall.sh/"
    )
    write_index(destination, index)


def import_abi(source, destination):
    destination.mkdir()
    document = html.parse(str(source), parser=html.HTMLParser(encoding="utf-8"))
    content = document.xpath('//*[contains(@class, "mw-parser-output")]')[0]
    index = {"System V ABI": "index.html"}
    for heading in content.xpath(".//h2[@id]|.//h3[@id]"):
        index[text(heading).lower()] = f'index.html#{heading.get("id")}'
    write_page(
        destination / "index.html",
        "System V ABI",
        content,
        "https://osdev.wiki/wiki/System_V_ABI?oldid=29518",
    )
    write_index(destination, index)


x86, syscalls, abi, destination = map(Path, sys.argv[1:])
import_x86(x86, destination / "x86-64")
import_syscalls(syscalls, destination / "syscalls")
import_abi(abi, destination / "abi")
