# -*- coding: utf-8 -*-
"""把 reports/verification 下的 Markdown 检测报告渲染为符合转换契约的 HTML。

只处理该报告实际用到的 Markdown 子集：标题、表格、代码块、列表、引用、段落、
行内加粗与行内代码。目的不是通用转换器，而是保证转出的 DOCX 版式可控。
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

CSS = """
/* 页面规则：正文页脚居中页码，封面无页码 */
@page { @bottom-center { content: "第 " counter(page) " 页"; } }
@page cover { @bottom-center { content: none; } }
section[role="cover"] { page: cover; }

body { font-family: "宋体", SimSun, serif; font-size: 12pt; line-height: 1.7; color: #1a1a1a; }

.cover-wrap { padding: 60pt 40pt 0 40pt; }
.cover-band { border-top: 4pt solid #1f3864; width: 120pt; margin-bottom: 28pt; }
.cover-cat { font-family: "黑体", SimHei, sans-serif; font-size: 13pt; color: #1f3864; letter-spacing: 0.16em; margin: 0 0 14pt 0; text-indent: 0; }
.cover-title { font-family: "黑体", SimHei, sans-serif; font-size: 30pt; font-weight: bold; color: #1f3864; margin: 0 0 8pt 0; text-indent: 0; line-height: 1.35; }
.cover-sub { font-size: 15pt; color: #5a5a5a; margin: 0 0 40pt 0; text-indent: 0; }
.cover-line { border-top: 1pt solid #bfbfbf; margin: 0 0 16pt 0; }
.cover-meta p { font-size: 10.5pt; color: #404040; margin: 0 0 6pt 0; text-indent: 0; }
.cover-note { font-size: 9.5pt; color: #7a7a7a; margin-top: 36pt; text-indent: 0; }

.toc-wrap { padding: 40pt 40pt 0 40pt; }
.toc-title { font-family: "黑体", SimHei, sans-serif; font-size: 18pt; font-weight: bold; color: #1f3864; margin: 0 0 18pt 0; text-indent: 0; }
.toc-list, .toc-list ol, .toc-list ul { list-style: none; list-style-type: none; padding-left: 0; margin: 0; }
.toc-list li { font-size: 11pt; line-height: 2.0; text-indent: 0; }
.toc-list ol { padding-left: 18pt; }
.toc-list ol li { font-size: 10.5pt; color: #404040; }
.toc-list a { color: #1f3864; text-decoration: none; }

.doc-body { padding: 0 40pt; }
h1 { font-family: "黑体", SimHei, sans-serif; font-size: 17pt; font-weight: bold; color: #ffffff; background-color: #1f3864; padding: 6pt 10pt; margin: 22pt 0 12pt 0; page-break-after: avoid; }
h2 { font-family: "黑体", SimHei, sans-serif; font-size: 13.5pt; font-weight: bold; color: #1f3864; border-left: 4pt solid #1f3864; padding-left: 8pt; margin: 16pt 0 8pt 0; page-break-after: avoid; }
p { font-size: 12pt; line-height: 1.75; margin: 0 0 8pt 0; text-indent: 2em; text-align: justify; }
p.lead { text-indent: 0; }
ul { margin: 0 0 8pt 0; padding-left: 24pt; }
li { font-size: 12pt; line-height: 1.7; margin-bottom: 3pt; }

table { width: 100%; border-collapse: collapse; margin: 8pt 0 12pt 0; }
th { font-family: "黑体", SimHei, sans-serif; font-size: 10.5pt; font-weight: bold; color: #1a1a1a; background-color: #e8edf5; border: 0.5pt solid #9aa8c0; padding: 5pt 6pt; text-align: left; }
td { font-size: 10.5pt; line-height: 1.55; border: 0.5pt solid #9aa8c0; padding: 5pt 6pt; vertical-align: top; }

.strong { font-weight: bold; }
.mono { font-family: "Consolas", "Courier New", monospace; font-size: 10pt; }
.quote { background-color: #f6f8fb; border-left: 3pt solid #8fa4c8; padding: 8pt 10pt; margin: 8pt 0 12pt 0; }
.quote p { text-indent: 0; font-size: 10.5pt; line-height: 1.6; margin: 0; color: #333333; }
.code-block { background-color: #f4f4f4; border: 0.5pt solid #d0d0d0; padding: 8pt 10pt; margin: 6pt 0 10pt 0; }
.code-block p { font-family: "Consolas", "Courier New", monospace; font-size: 9.5pt; line-height: 1.5; text-indent: 0; margin: 0 0 2pt 0; color: #1a1a1a; }
"""


def inline(text: str) -> str:
    out = html.escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r'<span class="strong">\1</span>', out)
    out = re.sub(r"`([^`]+?)`", r'<span class="mono">\1</span>', out)
    return out


def split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def main(src: str, dst: str, category: str) -> None:
    lines = Path(src).read_text(encoding="utf-8").splitlines()

    title = ""
    meta: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("- ") and title:
            meta.append(line[2:].strip())
        elif line == "---" and title:
            idx += 1
            break
        idx += 1
    body_lines = lines[idx:]

    blocks: list[str] = []
    toc: list[tuple[str, str, list[tuple[str, str]]]] = []
    chapter = 0
    current: list[tuple[str, str]] | None = None
    in_code = False
    code_buf: list[str] = []
    table_buf: list[str] = []
    list_buf: list[str] = []
    quote_buf: list[str] = []

    def flush_table() -> None:
        nonlocal table_buf
        if not table_buf:
            return
        rows = [r for r in table_buf if not re.match(r"^\|[\s:\-|]+\|?$", r.strip())]
        table_buf = []
        if not rows:
            return
        head, rest = rows[0], rows[1:]
        parts = ["<table>", "<tr>" + "".join(
            f'<th>{inline(c)}</th>' for c in split_row(head)) + "</tr>"]
        for row in rest:
            parts.append("<tr>" + "".join(
                f"<td>{inline(c)}</td>" for c in split_row(row)) + "</tr>")
        parts.append("</table>")
        blocks.append("\n".join(parts))

    def flush_list() -> None:
        nonlocal list_buf
        if list_buf:
            blocks.append("<ul>\n" + "\n".join(
                f"<li>{inline(item)}</li>" for item in list_buf) + "\n</ul>")
            list_buf = []

    def flush_quote() -> None:
        nonlocal quote_buf
        if quote_buf:
            blocks.append('<div class="quote"><p>' + inline(" ".join(quote_buf)) + "</p></div>")
            quote_buf = []

    def flush_code() -> None:
        nonlocal code_buf
        if code_buf:
            # 单段 + <br> 换行：转换引擎会把同一容器内多个 <p> 合并，并可能把以 # 开头的
            # 行当成标题吃掉，因此整块合成一段并避开首字符 #。
            joined = "<br>".join(html.escape(row) or "&nbsp;" for row in code_buf)
            if joined.startswith("#"):
                joined = "&nbsp;" + joined
            blocks.append(f'<div class="code-block"><p>{joined}</p></div>')
            code_buf = []

    for raw in body_lines:
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_table(); flush_list(); flush_quote()
            if in_code:
                flush_code()
                in_code = False
            else:
                in_code = True
                code_buf = []
            continue
        if in_code:
            code_buf.append(line)
            continue

        if not stripped:
            flush_table(); flush_list(); flush_quote()
            continue
        if stripped == "---":
            flush_table(); flush_list(); flush_quote()
            continue
        if stripped.startswith("|"):
            flush_list(); flush_quote()
            table_buf.append(stripped)
            continue
        if stripped.startswith("> "):
            flush_table(); flush_list()
            quote_buf.append(stripped[2:])
            continue
        if stripped.startswith("- "):
            flush_table(); flush_quote()
            list_buf.append(stripped[2:])
            continue
        if stripped.startswith("## "):
            flush_table(); flush_list(); flush_quote()
            chapter += 1
            anchor = f"section-{chapter}"
            heading = stripped[3:].strip()
            blocks.append(f'<h1 id="{anchor}">{inline(heading)}</h1>')
            current = []
            toc.append((anchor, heading, current))
            continue
        if stripped.startswith("### "):
            flush_table(); flush_list(); flush_quote()
            heading = stripped[4:].strip()
            blocks.append(f"<h2>{inline(heading)}</h2>")
            if current is not None:
                current.append((f"section-{chapter}", heading))
            continue

        flush_table(); flush_list(); flush_quote()
        blocks.append(f"<p>{inline(stripped)}</p>")

    flush_table(); flush_list(); flush_quote(); flush_code()

    toc_html = []
    for anchor, heading, subs in toc:
        if subs:
            inner = "".join(
                f'<li><a href="#{a}">{html.escape(h)}</a></li>' for a, h in subs)
            toc_html.append(
                f'<li><a href="#{anchor}">{html.escape(heading)}</a><ol>{inner}</ol></li>')
        else:
            toc_html.append(f'<li><a href="#{anchor}">{html.escape(heading)}</a></li>')

    meta_html = "".join(f"<p>{inline(m)}</p>" for m in meta)

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="docx-page-size" content="A4">
<title>{html.escape(title)}</title>
<style>{CSS}</style>
</head>
<body>

<section role="cover">
  <div class="cover-wrap">
    <div class="cover-band"></div>
    <p class="cover-cat">{html.escape(category)}</p>
    <p class="cover-title">{html.escape(title)}</p>
    <div class="cover-line"></div>
    <div class="cover-meta">{meta_html}</div>
    <p class="cover-note">本报告为验收测试报告的补充材料，全部结论来自真实进程与真实 HTTP 调用。</p>
  </div>
</section>

<section role="cover">
  <div class="toc-wrap">
    <nav class="doc-toc" aria-label="文档目录">
      <p class="toc-title">目 录</p>
      <ol class="toc-list">{"".join(toc_html)}</ol>
    </nav>
  </div>
</section>

<section role="body" class="doc-body" data-page-restart="1">
{chr(10).join(blocks)}
</section>
</body>
</html>
"""
    Path(dst).write_text(doc, encoding="utf-8")
    print(f"written {dst}  blocks={len(blocks)}  toc={len(toc)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "补充材料")
