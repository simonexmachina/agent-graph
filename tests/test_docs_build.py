from __future__ import annotations

from pathlib import Path

import pytest

import scripts.build_docs as build_docs
import scripts.serve_docs as serve_docs


def test_render_markdown_keeps_fenced_code_blocks_separate() -> None:
    markdown = """## First

```bash
echo hello
```

## Second
"""

    rendered, headings = build_docs.render_markdown(markdown)

    assert 'class="codehilite"' in rendered
    assert 'class="language-bash"' in rendered
    assert "tok-" in rendered
    assert "<h2 id=\"second\"><a class=\"anchor\" href=\"#second\" aria-label=\"Anchor link\">#</a>Second</h2>" in rendered
    assert [heading.text for heading in headings] == ["First", "Second"]


def test_render_inline_preserves_code_symbols() -> None:
    rendered = build_docs.render_inline("Use `run_auth_flow(cls) -> None` with `agentgraph auth <source>`.")

    assert "<code>run_auth_flow(cls) -&gt; None</code>" in rendered
    assert "<code>agentgraph auth &lt;source&gt;</code>" in rendered
    assert "-&amp;gt;" not in rendered
    assert "&amp;lt;source&amp;gt;" not in rendered


def test_build_writes_docs_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "docs"
    monkeypatch.setattr(build_docs, "DOCS_OUT", output_dir)

    build_docs.build()

    docs_css = (output_dir / "docs.css").read_text(encoding="utf-8")
    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    extending_html = (output_dir / "extending.html").read_text(encoding="utf-8")
    extension_distribution_html = (output_dir / "extension-distribution.html").read_text(encoding="utf-8")
    postgres_html = (output_dir / "postgresql.html").read_text(encoding="utf-8")
    commands_html = (output_dir / "commands" / "index.html").read_text(encoding="utf-8")
    search_html = (output_dir / "commands" / "search.html").read_text(encoding="utf-8")
    mcp_html = (output_dir / "mcp" / "index.html").read_text(encoding="utf-8")
    tester_install_html = (output_dir / "tester-extension-install.html").read_text(encoding="utf-8")
    connectors_redirect_html = (output_dir / "connectors.html").read_text(encoding="utf-8")
    redirect_html = (output_dir / "commands.html").read_text(encoding="utf-8")

    assert 'class="shell"' in index_html
    assert 'id="doc-search"' in index_html
    assert 'class="toc"' in index_html
    assert 'class="page-summary"' not in index_html
    assert 'class="language-bash"' not in index_html
    assert 'agentgraph<span class="tok-w"> </span>mcp-config' not in index_html
    assert ".doc .codehilite .tok-n" in docs_css
    assert "var(--code-name)" in docs_css
    assert ".doc pre .copy svg" in docs_css
    assert ">Commands</a>" in index_html
    assert 'href="postgresql.html"' in index_html
    assert "<section><h2>Configuration</h2><a class=\"nav-link\" href=\"configuration.html\">Configuration</a><a class=\"nav-link\" href=\"postgresql.html\">PostgreSQL</a><a class=\"nav-link\" href=\"extending.html\">Extending</a></section>" in index_html
    assert 'href="extending.html"' in index_html
    nav_html = index_html.split('<nav aria-label="Documentation">', 1)[1].split("</nav>", 1)[0]
    assert 'href="tester-extension-install.html"' not in nav_html
    assert 'href="privacy.html"' not in nav_html
    assert 'href="extension-distribution.html"' not in nav_html
    assert 'class="codehilite"' in extending_html
    assert 'class="tok-k"' in extending_html
    assert "current_user_id" in extending_html
    assert "Why extend AgentGraph" in extending_html
    assert "custom connectors" in extending_html
    assert "Chrome Web Store listing draft" in extension_distribution_html
    assert "http://localhost/*" in extension_distribution_html
    assert "agentgraph-extension.zip" in tester_install_html
    assert "Server settings" in tester_install_html
    assert 'content="0; url=extending.html"' in connectors_redirect_html
    assert "<h1>Commands</h1>" in commands_html
    assert "<h1>PostgreSQL</h1>" in postgres_html
    assert "default SQLite backend" in postgres_html
    assert "agentgraph search" in search_html
    assert "<code>agentgraph search</code>" in search_html
    assert 'href="../docs.css"' in search_html
    assert 'href="../index.html"' in search_html
    assert "MCP tools" in mcp_html
    assert 'content="0; url=commands/index.html"' in redirect_html


def test_build_requires_pygments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "docs"
    monkeypatch.setattr(build_docs, "DOCS_OUT", output_dir)
    monkeypatch.setattr(build_docs, "highlight", None)

    with pytest.raises(RuntimeError, match="Docs build requires Pygments"):
        build_docs.build()


def test_watch_snapshot_tracks_docs_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docs_src = tmp_path / "docs-src"
    scripts_dir = tmp_path / "scripts"
    docs_src.mkdir()
    scripts_dir.mkdir()
    (docs_src / "index.md").write_text("hello", encoding="utf-8")
    (scripts_dir / "build_docs.py").write_text("print('x')", encoding="utf-8")
    (scripts_dir / "serve_docs.py").write_text("print('y')", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    snapshot = serve_docs.snapshot_mtimes(serve_docs.watch_paths())

    assert Path("docs-src/index.md") in snapshot
    assert Path("scripts/build_docs.py") in snapshot
    assert Path("scripts/serve_docs.py") in snapshot
