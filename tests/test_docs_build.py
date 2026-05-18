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
    assert "<h2 id=\"second\">Second</h2>" in rendered
    assert [heading.text for heading in headings] == ["First", "Second"]


def test_build_writes_docs_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "docs"
    monkeypatch.setattr(build_docs, "DOCS_OUT", output_dir)

    build_docs.build()

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    commands_html = (output_dir / "commands" / "index.html").read_text(encoding="utf-8")
    redirect_html = (output_dir / "commands.html").read_text(encoding="utf-8")

    assert "sidebar-nav" in index_html
    assert "Edit page" in index_html
    assert "/commands/" in index_html
    assert "Command docs index" in commands_html
    assert 'content="0; url=/commands/"' in redirect_html
