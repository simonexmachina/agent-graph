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


def test_render_inline_preserves_link_query_separator() -> None:
    rendered = build_docs.render_inline("[Extension](https://example.com/detail?id=1&hl=en-AU)")

    assert 'href="https://example.com/detail?id=1&amp;hl=en-AU"' in rendered
    assert "&amp;amp;" not in rendered


def test_build_writes_docs_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "docs"
    monkeypatch.setattr(build_docs, "DOCS_OUT", output_dir)

    build_docs.build()

    docs_css = (output_dir / "docs.css").read_text(encoding="utf-8")
    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    install_html = (output_dir / "install.html").read_text(encoding="utf-8")
    extending_html = (output_dir / "extending.html").read_text(encoding="utf-8")
    rss_html = (output_dir / "rss.html").read_text(encoding="utf-8")
    slack_html = (output_dir / "slack.html").read_text(encoding="utf-8")
    commands_html = (output_dir / "commands" / "index.html").read_text(encoding="utf-8")
    search_html = (output_dir / "commands" / "search.html").read_text(encoding="utf-8")
    mcp_html = (output_dir / "mcp" / "index.html").read_text(encoding="utf-8")
    mcp_auth_html = (output_dir / "mcp" / "authenticate-provider.html").read_text(
        encoding="utf-8"
    )
    connectors_redirect_html = (output_dir / "connectors.html").read_text(encoding="utf-8")
    redirect_html = (output_dir / "commands.html").read_text(encoding="utf-8")

    assert 'class="shell"' in index_html
    assert "https://www.googletagmanager.com/gtag/js?id=G-36ETGXF6K5" in index_html
    assert "gtag('config', 'G-36ETGXF6K5');" in index_html
    assert 'id="doc-search"' in index_html
    assert 'class="toc"' in index_html
    assert 'class="page-summary"' not in index_html
    assert 'class="language-bash"' not in index_html
    assert 'agentgraph<span class="tok-w"> </span>mcp-config' not in index_html
    assert ".doc .codehilite .tok-n" in docs_css
    assert "var(--code-name)" in docs_css
    assert ".doc pre .copy svg" in docs_css
    assert ">Commands</a>" in index_html
    assert "<section><h2>Configuration</h2><a class=\"nav-link\" href=\"configuration.html\">Configuration</a><a class=\"nav-link\" href=\"rss.html\">RSS</a><a class=\"nav-link\" href=\"slack.html\">Slack auth</a><a class=\"nav-link\" href=\"extending.html\">Extending</a></section>" in index_html
    assert 'href="extending.html"' in index_html
    assert 'href="rss.html"' in index_html
    nav_html = index_html.split('<nav aria-label="Documentation">', 1)[1].split("</nav>", 1)[0]
    assert 'href="tester-extension-install.html"' not in nav_html
    assert 'href="privacy.html"' not in nav_html
    assert 'href="extension-distribution.html"' not in nav_html
    assert 'class="codehilite"' in extending_html
    assert 'class="tok-k"' in extending_html
    assert "current_user_id" in extending_html
    assert "Why extend AgentGraph" in extending_html
    assert "custom connectors" in extending_html
    assert "RSS" in extending_html
    assert "Add RSS and Atom feeds" in rss_html
    assert "feed.xml" in rss_html
    assert "platform=rss" in rss_html
    assert "AGENTGRAPH_SLACK_CLIENT_ID" in slack_html
    assert "Browser-session fallback" in slack_html
    assert "Quickstart" in index_html
    assert 'content="0; url=extending.html"' in connectors_redirect_html
    assert "<h1>Commands</h1>" in commands_html
    assert "After the extension is installed, continue with" in install_html
    assert "Authenticate connectors" not in install_html
    assert "agentgraph search" in search_html
    assert "<code>agentgraph search</code>" in search_html
    assert 'href="../docs.css"' in search_html
    assert 'href="../index.html"' in search_html
    assert 'class="page-nav-prev" href="index.html"' in search_html
    assert 'class="page-nav-next" href="query.html"' in search_html
    assert "MCP tools" in mcp_html
    assert "authenticate_provider_tool" in mcp_auth_html
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
