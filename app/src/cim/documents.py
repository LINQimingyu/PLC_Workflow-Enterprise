"""Local-only parsing with source coordinates; no network or model downloads."""
from __future__ import annotations
import csv
import io
import json
import zipfile
from pathlib import Path

MAX_BYTES = 20 * 1024 * 1024
MAX_TEXT = 8_000_000


def decode(raw):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("文本编码不支持")


def parse(name, raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("单文件超过 20 MiB")
    ext = Path(name).suffix.lower()
    if ext in {".docx",".xlsx"}:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.infolist())>10000 or sum(x.file_size for x in archive.infolist())>100*1024*1024:
                raise ValueError("Office 文件解压规模超出限制")
    chunks = []
    def add(location, text):
        if text.strip():
            for offset in range(0,len(text),12000):
                chunks.append({"location": location if offset==0 else location+f":offset:{offset}", "text": text[offset:offset+12000]})
    if ext in {".md", ".txt", ".json"}:
        for n, line in enumerate(decode(raw).splitlines(), 1):
            add(f"line:{n}", line)
    elif ext in {".csv", ".tsv"}:
        text = decode(raw)
        delimiter = "\t" if text.count("\t") > text.count(",") else ","
        for n, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), 1):
            add(f"row:{n}", " | ".join(row))
    elif ext == ".pdf":
        from pypdf import PdfReader
        for n, page in enumerate(PdfReader(io.BytesIO(raw)).pages, 1):
            text = page.extract_text() or ""
            for offset in range(0, len(text), 3000):
                add(f"page:{n}:offset:{offset}", text[offset:offset + 3000])
    elif ext == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(raw))
        for n, paragraph in enumerate(doc.paragraphs, 1):
            add(f"paragraph:{n}", paragraph.text)
        for t, table in enumerate(doc.tables, 1):
            for n, row in enumerate(table.rows, 1):
                add(f"table:{t}:row:{n}", " | ".join(c.text for c in row.cells))
    elif ext == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
        try:
            for sheet in book:
                for n, row in enumerate(sheet.iter_rows(values_only=True), 1):
                    add(f"sheet:{sheet.title}:row:{n}", " | ".join(str(v) if v is not None else "" for v in row))
                    if len(chunks) > 100_000:
                        raise ValueError("工作簿行数超出索引限制")
        finally:
            book.close()
    elif ext in {".gxw", ".gx3"}:
        return [], "native_engineering_required"
    else:
        return [], "unsupported_format"
    if sum(len(c["text"]) for c in chunks) > MAX_TEXT:
        raise ValueError("解析文本超过索引限制，请按工段拆分")
    return chunks, "indexed" if chunks else "empty_or_ocr_required"
