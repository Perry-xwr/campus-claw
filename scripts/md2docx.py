"""把验收报告 Markdown 转成 Word，供不装 Markdown 阅读器的环境打开。

只覆盖报告里实际用到的语法：标题、段落、表格、代码块、引用块、有序/无序列表，
以及行内的 **加粗**、`代码`、[文字](链接)。刻意不引第三方 Markdown 库——
转换规则一屏能读完，出问题时能直接改这里。

用法：
    python scripts/md2docx.py reports/xxx.md reports/xxx.docx
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")
CJK_FONT = "等线"
LATIN_FONT = "Consolas"


def _set_font(run, name: str = CJK_FONT) -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def add_inline(paragraph, text: str, *, size: float = 10.5, mono: bool = False) -> None:
    """按行内标记切分写入，保持加粗与代码的原样观感。"""
    for piece in INLINE.split(text):
        if not piece:
            continue
        if len(piece) > 4 and piece.startswith("**") and piece.endswith("**"):
            run = paragraph.add_run(piece[2:-2])
            run.bold = True
            _set_font(run)
            run.font.size = Pt(size)
        elif len(piece) > 2 and piece.startswith("`") and piece.endswith("`"):
            run = paragraph.add_run(piece[1:-1])
            _set_font(run, LATIN_FONT)
            run.font.size = Pt(size - 0.5)
            run.font.color.rgb = RGBColor(0x9C, 0x27, 0x1B)
        elif piece.startswith("[") and "](" in piece:
            run = paragraph.add_run(piece[1 : piece.index("]")])
            _set_font(run)
            run.font.size = Pt(size)
            run.font.color.rgb = RGBColor(0x1A, 0x4F, 0x9C)
        else:
            run = paragraph.add_run(piece)
            _set_font(run, LATIN_FONT if mono else CJK_FONT)
            run.font.size = Pt(size - 0.5 if mono else size)


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def convert(md_path: Path, docx_path: Path) -> tuple[int, int]:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = CJK_FONT
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), CJK_FONT)

    paragraphs = 0
    tables = 0
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()

        if not line.strip():
            i += 1
            continue

        # 代码块
        if line.lstrip().startswith("```"):
            i += 1
            block: list[str] = []
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                block.append(lines[i].rstrip("\n"))
                i += 1
            i += 1
            para = doc.add_paragraph()
            para.paragraph_format.left_indent = Pt(14)
            para.paragraph_format.space_before = Pt(4)
            para.paragraph_format.space_after = Pt(8)
            run = para.add_run("\n".join(block))
            run.font.name = LATIN_FONT
            run.font.size = Pt(9)
            paragraphs += 1
            continue

        # 表格：当前行与下一行都是竖线开头，且第二行是分隔线
        if line.startswith("|") and i + 1 < len(lines) and re.match(
            r"^\|[\s:\-|]+\|$", lines[i + 1].strip()
        ):
            header = split_row(line)
            i += 2
            body: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append(split_row(lines[i]))
                i += 1
            cols = len(header)
            table = doc.add_table(rows=1, cols=cols)
            table.style = "Light Grid Accent 1"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            for index, text in enumerate(header):
                cell = table.rows[0].cells[index]
                cell.text = ""
                add_inline(cell.paragraphs[0], text, size=9.5)
                for run in cell.paragraphs[0].runs:
                    run.bold = True
            for row in body:
                cells = table.add_row().cells
                for index in range(cols):
                    value = row[index] if index < len(row) else ""
                    cells[index].text = ""
                    add_inline(cells[index].paragraphs[0], value, size=9.5)
            tables += 1
            doc.add_paragraph()
            paragraphs += 1
            continue

        # 标题
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            para = doc.add_paragraph()
            para.paragraph_format.space_before = Pt(14 if level <= 2 else 10)
            para.paragraph_format.space_after = Pt(6)
            add_inline(para, heading.group(2), size=18 - 1.6 * level)
            for run in para.runs:
                run.bold = True
            if level == 1:
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            i += 1
            paragraphs += 1
            continue

        # 引用块（连续多行合并成一段）
        if line.startswith(">"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                block.append(lines[i].lstrip()[1:].strip())
                i += 1
            para = doc.add_paragraph()
            para.paragraph_format.left_indent = Pt(16)
            add_inline(para, " ".join(piece for piece in block if piece), size=10)
            for run in para.runs:
                run.font.color.rgb = RGBColor(0x44, 0x4A, 0x52)
            paragraphs += 1
            continue

        # 列表
        bullet = re.match(r"^\s*([-*]|\d+[.)])\s+(.*)$", line)
        if bullet:
            marker = "" if bullet.group(1) in "-*" else bullet.group(1)
            text = bullet.group(2)
            para = doc.add_paragraph()
            para.paragraph_format.left_indent = Pt(18)
            para.paragraph_format.space_after = Pt(2)
            add_inline(para, f"{marker} {text}" if marker else f"· {text}")
            i += 1
            paragraphs += 1
            continue

        # 普通段落
        para = doc.add_paragraph()
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.25
        add_inline(para, line.strip())
        i += 1
        paragraphs += 1

    doc.save(str(docx_path))
    return paragraphs, tables


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    source, target = Path(argv[1]), Path(argv[2])
    if not source.exists():
        print(f"找不到源文件：{source}")
        return 2
    paragraphs, tables = convert(source, target)
    size = target.stat().st_size
    print(f"已生成 {target}（{paragraphs} 段、{tables} 张表、{size:,} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
