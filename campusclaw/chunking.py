"""LangChain-based text segmentation with traceable character offsets."""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int
    end: int
    text: str
    offset_basis: str


class StrategyError(ValueError):
    pass


def validate_strategy(raw: object) -> dict:
    if raw is None:
        return {"strategy": "auto"}
    if not isinstance(raw, dict):
        raise StrategyError("strategy must be an object")
    name = raw.get("strategy", "auto")
    if name == "auto":
        return {"strategy": "auto"}
    if name == "hierarchy":
        return {"strategy": "hierarchy"}
    if name != "custom":
        raise StrategyError("unknown strategy")
    try:
        size = int(raw.get("chunk_size", 800))
        ratio = float(raw.get("overlap_ratio", 0.1))
    except (TypeError, ValueError) as exc:
        raise StrategyError("invalid chunk size or overlap") from exc
    if not (100 <= size <= 2000 and 0 <= ratio <= 0.5):
        raise StrategyError("custom size must be 100..2000 and overlap 0..0.5")
    separator = raw.get("separator", "blankline")
    if separator not in ("blankline", "newline", "sentence"):
        raise StrategyError("separator must be blankline, newline or sentence")
    return {
        "strategy": "custom", "chunk_size": size,
        "overlap_ratio": ratio, "separator": separator,
        "remove_urls": bool(raw.get("remove_urls", False)),
        "remove_emails": bool(raw.get("remove_emails", False)),
        "collapse_whitespace": bool(raw.get("collapse_whitespace", False)),
    }


def _preprocess(body: str, strategy: dict) -> tuple[str, str]:
    if strategy["strategy"] != "custom":
        return body, "original"
    text = body
    if strategy["remove_urls"]:
        text = re.sub(r"https?://[^\s]+", "", text)
    if strategy["remove_emails"]:
        text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "", text)
    if strategy["collapse_whitespace"]:
        text = re.sub(r"\s+", " ", text)
    return text, "processed" if text != body else "original"


def _split_section(text: str, base: int, size: int, overlap: int,
                   separators: list[str], basis: str) -> list[Chunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size, chunk_overlap=overlap, separators=separators,
        keep_separator="end", add_start_index=True, strip_whitespace=False,
    )
    out: list[Chunk] = []
    for doc in splitter.create_documents([text]):
        part = doc.page_content
        if not part.strip():
            continue
        local = doc.metadata.get("start_index", -1)
        if local < 0 or text[local:local + len(part)] != part:
            raise StrategyError("chunk offset could not be verified")
        out.append(Chunk(0, base + local, base + local + len(part), part, basis))
    return out


def split_body(body: str, raw_strategy: object = None) -> list[Chunk]:
    strategy = validate_strategy(raw_strategy)
    text, basis = _preprocess(body, strategy)
    if not text.strip():
        return []
    name = strategy["strategy"]
    if name == "custom":
        chosen = {"blankline": "\n\n", "newline": "\n", "sentence": "。"}[strategy["separator"]]
        separators = [chosen, ""]
        size = strategy["chunk_size"]
        overlap = round(size * strategy["overlap_ratio"])
        parts = _split_section(text, 0, size, overlap, separators, basis)
    elif name == "hierarchy":
        headings = list(re.finditer(r"(?m)^#{1,3}[ \t]+[^\n]+", text))
        boundaries = [0] + [m.start() for m in headings if m.start() != 0] + [len(text)]
        boundaries = sorted(set(boundaries))
        parts = []
        for start, end in zip(boundaries, boundaries[1:]):
            parts.extend(_split_section(text[start:end], start, 800, 80,
                                        ["\n\n", "\n", "。", ""], basis))
    else:
        parts = _split_section(text, 0, 800, 80, ["\n\n", "\n", "。", ""], basis)
    return [Chunk(i, c.start, c.end, c.text, c.offset_basis)
            for i, c in enumerate(parts, 1)]
