"""Server import hygiene tests."""

from __future__ import annotations

import subprocess
import sys


def test_server_app_import_does_not_load_embedding_stack() -> None:
    script = """
import json
import sys
import agentgraph.server.app
print(json.dumps({
    "fastembed": "fastembed" in sys.modules,
    "embeddings": "agentgraph.graph.embeddings" in sys.modules,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == '{"fastembed": false, "embeddings": false}'
