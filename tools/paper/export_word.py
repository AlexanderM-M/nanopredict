"""Export the working manuscript using the supplied Bioinformatics Advances template.

Requires pandoc and lxml. Run from any directory; output remains an author draft.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import posixpath
import subprocess
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

from lxml import etree as ET

ROOT = Path(__file__).resolve().parents[2]
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{" + NS["w"] + "}"


def text(element):
    return "".join(element.itertext()) if element.tag == W + "t" else "".join(
        node.text or "" for node in element.findall(".//w:t", NS)
    )


def child(parent, name, **attrs):
    return ET.SubElement(parent, W + name, {W + key: str(value) for key, value in attrs.items()})


def style(paragraph, name):
    properties = paragraph.find("w:pPr", NS)
    if properties is None:
        properties = ET.Element(W + "pPr")
        paragraph.insert(0, properties)
    for item in properties.findall("w:pStyle", NS):
        properties.remove(item)
    properties.insert(0, ET.Element(W + "pStyle", {W + "val": name}))
    return properties


def paragraph(value, name):
    p = ET.Element(W + "p")
    style(p, name)
    child(child(p, "r"), "t").text = value
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "paper/manuscript.md")
    parser.add_argument("--template", type=Path, default=ROOT / "paper/bioadv-word-template.docx")
    parser.add_argument("--output", type=Path, default=ROOT / "paper/NanoPredict_manuscript_bioadv.docx")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        converted = Path(temporary) / "converted.docx"
        subprocess.run([
            "pandoc", str(args.source), "--from=markdown-implicit_figures", "--to=docx",
            "--standalone", "--metadata=lang:en-GB",
            "--resource-path=" + str(args.source.resolve().parent),
            "--reference-doc=" + str(args.template), "--output=" + str(converted),
        ], check=True)
        with ZipFile(converted) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
    document = ET.fromstring(contents["word/document.xml"])
    body = document.find("w:body", NS)
    original = list(body)
    introduction = next(i for i, item in enumerate(original) if text(item) == "Introduction")
    front = original[:introduction]
    single = deepcopy(body.find("w:sectPr", NS))

    def section(columns):
        result = deepcopy(single)
        kind = result.find("w:type", NS)
        if kind is None:
            kind = ET.Element(W + "type")
            result.insert(0, kind)
        kind.set(W + "val", "continuous")
        result.find("w:cols", NS).set(W + "num", str(columns))
        return result

    def boundary(columns):
        p = paragraph("", "Normal")
        properties = p.find("w:pPr", NS)
        child(properties, "spacing", before=0, after=0, line=20, lineRule="exact")
        properties.append(section(columns))
        return p

    with ZipFile(args.template) as archive:
        template = ET.fromstring(archive.read("word/document.xml"))
    title_box = deepcopy(template.find("w:body/w:tbl", NS))
    cell = title_box.find("w:tr/w:tc", NS)
    for item in list(cell):
        if item.tag != W + "tcPr":
            cell.remove(item)
    cell.append(paragraph("Software", "Subtitle"))
    for item in front:
        value = text(item)
        if not value:
            continue
        if value.startswith("Running head:"):
            continue
        if value.startswith("NanoPredict:"):
            target = "Title"
        elif value.startswith("Provisional authors:"):
            target = "Author-Group"
        elif value.startswith("Affiliations:"):
            target = "Author-Affiliation"
        elif value.startswith("Corresponding author:"):
            target = "corrs-au"
        elif value == "Abstract":
            target = "Abstract-Head"
        elif value.startswith("Draft for"):
            target = "article-info"
        else:
            target = "Abstract-Text"
        item = deepcopy(item)
        style(item, target)
        cell.append(item)
    for item in list(body):
        body.remove(item)
    body.append(paragraph("Bioinformatics Advances | Application Note | Author draft", "article-info"))
    body.append(title_box)
    body.append(boundary(1))

    references = False
    first = True
    wide = False
    for item in original[introduction:]:
        if item.tag == W + "sectPr":
            continue
        value = text(item)
        pstyle = item.find("w:pPr/w:pStyle", NS)
        heading = pstyle is not None and pstyle.get(W + "val", "").startswith("Heading")
        if heading:
            references = value == "References" or references
            style(item, "RefHead" if references else "Heading1")
            first = True
        elif item.tag == W + "tbl":
            widths = [2000, 1000, 1800, 1800, 3164]
            for column, width in zip(item.findall("w:tblGrid/w:gridCol", NS), widths):
                column.set(W + "w", str(width))
            for row_index, row in enumerate(item.findall("w:tr", NS)):
                for table_cell, width in zip(row.findall("w:tc", NS), widths):
                    cell_width = table_cell.find("w:tcPr/w:tcW", NS)
                    if cell_width is not None:
                        cell_width.set(W + "w", str(width))
                        cell_width.set(W + "type", "dxa")
                    for p in table_cell.findall("w:p", NS):
                        style(p, "TableColumnhead" if row_index == 0 else "Tablebody")
        elif value.startswith("Table 1."):
            body.append(boundary(2))
            wide = True
            child(style(item, "Tablecaption"), "keepNext")
        elif item.find(".//w:drawing", NS) is not None:
            body.append(boundary(2))
            wide = True
            child(style(item, "Normal"), "keepNext")
        elif value.startswith("Figure 1."):
            style(item, "FigureCaption")
        else:
            style(item, "RefText" if references else "para-first" if first else "para1")
            first = False
        body.append(item)
        if wide and (item.tag == W + "tbl" or value.startswith("Figure 1.")):
            body.append(boundary(1))
            wide = False
    body.append(section(2))
    contents["word/document.xml"] = ET.tostring(document, xml_declaration=True, encoding="UTF-8", standalone=True)
    running = next(text(item).split(": ", 1)[1] for item in front if text(item).startswith("Running head:"))
    for name in contents:
        if name.startswith("word/header") and name.endswith(".xml"):
            root = ET.fromstring(contents[name])
            for node in root.findall(".//w:t", NS):
                if node.text == "Article short title":
                    node.text = running
            contents[name] = ET.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    # Pandoc can carry unused example artwork from the reference package.
    referenced_parts = set()
    for name, content in contents.items():
        if name.endswith(".rels"):
            directory = posixpath.dirname(posixpath.dirname(name))
            for relationship in ET.fromstring(content):
                if relationship.get("TargetMode") != "External":
                    referenced_parts.add(posixpath.normpath(posixpath.join(
                        directory, relationship.get("Target", "")
                    )))
    for name in list(contents):
        if name.startswith("word/media/") and name not in referenced_parts:
            del contents[name]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, "w", ZIP_DEFLATED) as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    print(args.output)


if __name__ == "__main__":
    main()
