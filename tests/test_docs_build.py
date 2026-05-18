from __future__ import annotations

from pathlib import Path

import pytest

import scripts.build_docs as build_docs


def test_render_markdown_keeps_fenced_code_blocks_separate() -> None:
    markdown = """## First

```bash
echo hello
```

## Second
"""

    rendered, headings = build_docs.render_markdown(markdown)

    assert "<pre><code class=\"language-bash\">echo hello</code></pre>" in rendered
    assert "<h2 id=\"second\"><a class=\"anchor\" href=\"#second\" aria-label=\"Anchor link\">#</a>Second</h2>" in rendered
    assert [heading.text for heading in headings] == ["First", "Second"]


def test_build_writes_docs_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "docs"
    monkeypatch.setattr(build_docs, "DOCS_OUT", output_dir)

    build_docs.build()

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    commands_html = (output_dir / "commands" / "index.html").read_text(encoding="utf-8")
    search_html = (output_dir / "commands" / "search.html").read_text(encoding="utf-8")
    mcp_html = (output_dir / "mcp" / "index.html").read_text(encoding="utf-8")
    redirect_html = (output_dir / "commands.html").read_text(encoding="utf-8")

    assert 'class="shell"' in index_html
    assert 'id="doc-search"' in index_html
    assert 'class="toc"' in index_html
    assert ">Commands</a>" in index_html
    assert "<h1>Commands</h1>" in commands_html
    assert "agentgraph search" in search_html
    assert "<code>agentgraph search</code>" in search_html
    assert 'href="../docs.css"' in search_html
    assert 'href="../index.html"' in search_html
    assert "MCP tools" in mcp_html
    assert 'content="0; url=commands/index.html"' in redirect_html
