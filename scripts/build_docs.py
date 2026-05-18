from __future__ import annotations

import html
import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_SRC = ROOT / "docs-src"
DOCS_OUT = ROOT / "docs"
GITHUB_ROOT = "https://github.com/simonexmachina/agent-graph/blob/main"
SITE_TITLE = "AgentGraph documentation"
SECTION_ORDER = {"Start": 10, "Reference": 20}


@dataclass(frozen=True)
class PageMeta:
    source_path: Path
    output_path: Path
    title: str
    description: str
    nav_title: str
    section: str
    order: int
    summary: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    slug: str


@dataclass(frozen=True)
class Page:
    meta: PageMeta
    body: str
    headings: tuple[Heading, ...]


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "section"


def parse_frontmatter(text: str) -> tuple[PageMeta, str]:
    if not text.startswith("+++\n"):
        raise ValueError("Missing TOML frontmatter")
    _, frontmatter, body = text.split("+++\n", 2)
    data = tomllib.loads(frontmatter)

    source_path = Path(str(data["source_path"]))
    aliases = tuple(str(alias) for alias in data.get("aliases", []))
    return (
        PageMeta(
            source_path=source_path,
            output_path=Path(str(data["output"])),
            title=str(data["title"]),
            description=str(data["description"]),
            nav_title=str(data["nav_title"]),
            section=str(data["section"]),
            order=int(data["order"]),
            summary=str(data["summary"]),
            aliases=aliases,
        ),
        body.strip() + "\n",
    )


def render_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", lambda m: f"<code>{html.escape(m.group(1))}</code>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def render_markdown(body: str) -> tuple[str, tuple[Heading, ...]]:
    lines = body.splitlines()
    parts: list[str] = []
    headings: list[Heading] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):
            fence = "```"
            language = stripped[3:].strip()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != fence:
                code_lines.append(lines[i])
                i += 1
            parts.append(
                "<pre><code"
                + (f' class="language-{html.escape(language, quote=True)}"' if language else "")
                + f">{html.escape('\n'.join(code_lines))}</code></pre>"
            )
            i += 1
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2).strip()
            slug = slugify(text)
            headings.append(Heading(level=level, text=text, slug=slug))
            parts.append(f"<h{level} id=\"{slug}\">{render_inline(text)}</h{level}>")
            i += 1
            continue

        if stripped.startswith("<"):
            block_lines = [line]
            i += 1
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                if not next_stripped:
                    block_lines.append(next_line)
                    i += 1
                    continue
                if (
                    next_stripped.startswith("<")
                    or next_stripped.startswith(">")
                    or next_stripped.startswith("- ")
                    or re.match(r"^\d+\.\s+", next_stripped)
                ):
                    block_lines.append(next_line)
                    i += 1
                    continue
                break
            parts.append("\n".join(block_lines))
            continue

        if stripped.startswith("> "):
            quote_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("> "):
                quote_lines.append(lines[i].strip()[2:])
                i += 1
            parts.append("<blockquote>" + render_inline(" ".join(quote_lines)) + "</blockquote>")
            continue

        if stripped.startswith("- "):
            items: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            parts.append(
                "<ul>" + "".join(f"<li>{render_inline(item)}</li>" for item in items) + "</ul>"
            )
            continue

        if re.match(r"^\d+\.\s+", stripped):
            items = []
            while i < len(lines):
                match = re.match(r"^\d+\.\s+(.*)$", lines[i].strip())
                if not match:
                    break
                items.append(match.group(1))
                i += 1
            parts.append(
                "<ol>" + "".join(f"<li>{render_inline(item)}</li>" for item in items) + "</ol>"
            )
            continue

        paragraph_lines = [stripped]
        i += 1
        while i < len(lines):
            next_line = lines[i].strip()
            if not next_line:
                break
            if next_line.startswith(("```", "#", "<", "> ", "- ")) or re.match(
                r"^\d+\.\s+", next_line
            ):
                break
            paragraph_lines.append(next_line)
            i += 1
        parts.append(f"<p>{render_inline(' '.join(paragraph_lines))}</p>")

    return "\n\n".join(parts), tuple(headings)


def load_pages() -> list[Page]:
    pages: list[Page] = []
    for source_path in sorted(DOCS_SRC.rglob("*.md")):
        text = source_path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        rendered_body, headings = render_markdown(body)
        pages.append(Page(meta=meta, body=rendered_body, headings=headings))
    return sorted(
        pages,
        key=lambda page: (
            SECTION_ORDER.get(page.meta.section, 999),
            page.meta.order,
            str(page.meta.output_path),
        ),
    )


def build_global_nav(pages: list[Page], current_page: Page) -> str:
    grouped: dict[str, list[Page]] = {}
    section_order: list[str] = []
    for page in pages:
        if page.meta.section not in grouped:
            grouped[page.meta.section] = []
            section_order.append(page.meta.section)
        grouped[page.meta.section].append(page)

    section_blocks: list[str] = []
    for section in section_order:
        links = ""
        for page in grouped[section]:
            current_attr = ' aria-current="page"' if page.meta.output_path == current_page.meta.output_path else ""
            links += (
                f'<li><a href="{page_permalink(page.meta)}"{current_attr}>{page.meta.nav_title}</a></li>'
            )
        section_blocks.append(
            f'<section class="sidebar-section"><h2>{html.escape(section)}</h2><ul>{links}</ul></section>'
        )
    return "\n".join(section_blocks)


def build_on_page_nav(page: Page) -> str:
    items = [heading for heading in page.headings if heading.level == 2]
    if not items:
        return "<p class=\"on-page-empty\">This page is short.</p>"
    return "<ul>" + "".join(
        f'<li><a href="#{heading.slug}">{html.escape(heading.text)}</a></li>' for heading in items
    ) + "</ul>"


def page_permalink(meta: PageMeta) -> str:
    output = meta.output_path.as_posix()
    if output == "index.html":
        return "/"
    if output.endswith("/index.html"):
        return "/" + output[: -len("index.html")]
    return "/" + output


def build_prev_next(pages: list[Page], index: int) -> str:
    links: list[str] = []
    if index > 0:
        previous = pages[index - 1]
        links.append(
            f'<a class="pager-link" href="{page_permalink(previous.meta)}"><span>Previous</span><strong>{html.escape(previous.meta.nav_title)}</strong></a>'
        )
    else:
        links.append('<span class="pager-link pager-link-empty"></span>')
    if index + 1 < len(pages):
        next_page = pages[index + 1]
        links.append(
            f'<a class="pager-link" href="{page_permalink(next_page.meta)}"><span>Next</span><strong>{html.escape(next_page.meta.nav_title)}</strong></a>'
        )
    else:
        links.append('<span class="pager-link pager-link-empty"></span>')
    return "<nav class=\"page-pager\">" + "".join(links) + "</nav>"


def build_page(page: Page, pages: list[Page], index: int, nav_html: str) -> str:
    source_href = f"{GITHUB_ROOT}/{page.meta.source_path.as_posix()}"
    title = html.escape(page.meta.title)
    description = html.escape(page.meta.description, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title} - AgentGraph</title>
  <meta name="description" content="{description}" />
  <link rel="stylesheet" href="/docs.css" />
</head>
<body>
  <div class="site-shell">
    <aside class="site-sidebar">
      <a class="sidebar-brand" href="/">Agent<span>Graph</span></a>
      <p class="sidebar-copy">Local graph tooling for AI agents: browser-driven capture, connector polling, CLI workflows, and MCP access over the same data.</p>
      <nav class="sidebar-nav" aria-label="Documentation">
{nav_html}
      </nav>
      <div class="sidebar-footer">
        <a href="https://github.com/simonexmachina/agent-graph">GitHub</a>
        <a href="/privacy.html">Privacy</a>
      </div>
    </aside>

    <main class="page-shell">
      <header class="page-header">
        <div class="utility-links">
          <a href="/">Home</a>
          <a href="https://github.com/simonexmachina/agent-graph">GitHub</a>
          <a href="{source_href}">Edit page</a>
        </div>
        <div class="logo-slot" aria-label="Logo placeholder">Logo</div>
      </header>

      <div class="page-grid">
        <article class="page-content">
          <h1>{title}</h1>
          <p class="page-summary">{html.escape(page.meta.summary)}</p>
{page.body}
{build_prev_next(pages, index)}
        </article>

        <aside class="page-aside">
          <div class="on-page-card">
            <h2>On this page</h2>
            {build_on_page_nav(page)}
          </div>
        </aside>
      </div>
    </main>
  </div>
</body>
</html>
"""


def write_redirect(alias: Path, target: str) -> None:
    alias.parent.mkdir(parents=True, exist_ok=True)
    alias.write_text(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="refresh" content="0; url={html.escape(target, quote=True)}" />
  <link rel="canonical" href="{html.escape(target, quote=True)}" />
</head>
<body></body>
</html>
""",
        encoding="utf-8",
    )


def copy_static_assets() -> None:
    DOCS_OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "docs-src" / "docs.css", DOCS_OUT / "docs.css")


def build() -> None:
    pages = load_pages()
    copy_static_assets()

    for index, page in enumerate(pages):
        nav_html = build_global_nav(pages, page)
        output_path = DOCS_OUT / page.meta.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(build_page(page, pages, index, nav_html), encoding="utf-8")
        for alias in page.meta.aliases:
            write_redirect(DOCS_OUT / alias, page_permalink(page.meta))


if __name__ == "__main__":
    build()
