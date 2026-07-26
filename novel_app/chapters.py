"""Chapter-title detection for imported plain-text and Markdown novels."""

from __future__ import annotations

import re
from dataclasses import dataclass


CHINESE_HEADING = re.compile(
    r"^\s*(第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*"
    r"[章回卷部篇](?:(?:\s*[：:、.\-—]\s*|\s+)[^\r\n]*)?)\s*$"
)
MARKDOWN_HEADING = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$")
ENGLISH_HEADING = re.compile(
    r"^\s*((?:chapter|book|part)\s+[0-9ivxlcdm]+(?:\s*[:.\-—]\s*|\s+)?"
    r"[^\r\n]*)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedChapter:
    title: str
    content: str


def chapter_title(line: str) -> str | None:
    """Return a normalized title when a line looks like a chapter heading."""
    value = line.strip()
    for pattern in (MARKDOWN_HEADING, CHINESE_HEADING, ENGLISH_HEADING):
        match = pattern.match(value)
        if match:
            return match.group(1).strip()
    return None


def parse_novel_chapters(text: str, fallback_title: str) -> list[ParsedChapter]:
    """Split imported text at recognized headings, preserving chapter bodies."""
    lines = text.splitlines(keepends=True)
    parsed: list[ParsedChapter] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        content = "".join(current_lines).strip()
        if current_title is not None:
            parsed.append(ParsedChapter(current_title, content))
        elif content:
            parsed.append(ParsedChapter("序章", content))
        current_lines = []

    for line in lines:
        detected = chapter_title(line)
        if detected:
            flush()
            current_title = detected
        else:
            current_lines.append(line)
    flush()

    if not parsed:
        return [ParsedChapter(fallback_title or "导入原稿", text.strip())]
    if len(parsed) == 1 and parsed[0].title == "序章":
        return [ParsedChapter(fallback_title or "导入原稿", parsed[0].content)]
    return parsed
