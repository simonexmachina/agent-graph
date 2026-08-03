"""Browser-level contracts for the Cytoscape viewer layout."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, cast
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright


class _ViewerFixtureServer(ThreadingHTTPServer):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    viewer_html: bytes


class _ViewerFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        server = cast(_ViewerFixtureServer, self.server)
        path = urlsplit(self.path).path
        if path == "/viewer":
            self._send(200, "text/html; charset=utf-8", server.viewer_html)
        elif path == "/api/cli/meta":
            self._send(200, "application/json", {"entity_types": ["Document"], "platforms": []})
        elif path == "/api/cli/browse/nodes":
            self._send(200, "application/json", {"data": server.nodes, "has_more": False})
        elif path == "/api/cli/browse/edges":
            self._send(200, "application/json", {"edges": server.edges})
        else:
            self._send(404, "application/json", {"detail": "not found"})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, content_type: str, body: bytes | dict[str, Any]) -> None:
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@contextmanager
def _serve_viewer(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Iterator[str]:
    server = _ViewerFixtureServer(("127.0.0.1", 0), _ViewerFixtureHandler)
    server.nodes = nodes
    server.edges = edges
    server.viewer_html = Path("agentgraph/server/static/viewer.html").read_bytes()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/viewer"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    yield page
    page.close()


def _node(index: int, label: str) -> dict[str, Any]:
    return {
        "id": f"node-{index}",
        "entity_type": "Document",
        "platform": "test",
        "platform_entity_id": str(index),
        "viewer_label": label,
        "content": "",
    }


def _wait_for_graph(page: Page, url: str, node_count: int) -> None:
    page.goto(url)
    page.wait_for_function(
        "count => window.__agentGraphViewer.cy.nodes().length === count",
        arg=node_count,
    )
    page.wait_for_timeout(250)


def _layout_metrics(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const cy = window.__agentGraphViewer.cy;
          const nodes = cy.nodes().toArray();
          const boxes = nodes.map(node => ({ id: node.id(), box: node.renderedBoundingBox({ includeLabels: true, includeOverlays: false }) }));
          let overlaps = 0;
          for (let i = 0; i < boxes.length; i += 1) {
            for (let j = i + 1; j < boxes.length; j += 1) {
              const a = boxes[i].box;
              const b = boxes[j].box;
              if (a.x1 < b.x2 && a.x2 > b.x1 && a.y1 < b.y2 && a.y2 > b.y1) overlaps += 1;
            }
          }
          return { overlaps, boxes };
        }"""
    )


def test_edge_free_graph_uses_a_non_overlapping_grid(page: Page) -> None:
    nodes = [_node(index, f"Isolated document {index}") for index in range(50)]
    with _serve_viewer(nodes, []) as url:
        _wait_for_graph(page, url, len(nodes))
        metrics = _layout_metrics(page)

    assert metrics["overlaps"] == 0


def test_node_bounds_and_labels_remain_capped_across_zoom(page: Page) -> None:
    nodes = [_node(1, "A deliberately long document title that needs more than three lines to display")]
    with _serve_viewer(nodes, []) as url:
        _wait_for_graph(page, url, len(nodes))
        measurements = page.evaluate(
            """() => {
              const cy = window.__agentGraphViewer.cy;
              const node = cy.nodes()[0];
              return [0.5, 1, 2].map(zoom => {
                cy.zoom({ level: zoom, renderedPosition: node.renderedPosition() });
                return {
                  body: node.renderedBoundingBox({ includeLabels: false, includeOverlays: false }),
                  all: node.renderedBoundingBox({ includeLabels: true, includeOverlays: false }),
                };
              });
            }"""
        )

    for measurement in measurements:
        body = measurement["body"]
        all_bounds = measurement["all"]
        assert all_bounds["w"] <= 176
        assert all_bounds["h"] <= 72
        assert all_bounds["x1"] >= body["x1"]
        assert all_bounds["x2"] <= body["x2"]
        assert all_bounds["y1"] >= body["y1"]
        assert all_bounds["y2"] <= body["y2"]


def test_selection_and_hover_do_not_move_graph_geometry(page: Page) -> None:
    nodes = [_node(1, "Hover target"), _node(2, "Other node")]
    with _serve_viewer(nodes, []) as url:
        _wait_for_graph(page, url, len(nodes))
        before = page.evaluate(
            """() => window.__agentGraphViewer.cy.nodes().map(node => ({
              id: node.id(), position: node.position(), box: node.renderedBoundingBox({ includeLabels: true, includeOverlays: false }),
            }))"""
        )
        page.evaluate("() => window.__agentGraphViewer.cy.nodes()[0].select()")
        after_selection = page.evaluate(
            """() => window.__agentGraphViewer.cy.nodes().map(node => ({
              id: node.id(), position: node.position(), box: node.renderedBoundingBox({ includeLabels: true, includeOverlays: false }),
            }))"""
        )
        canvas = page.locator("#cy").bounding_box()
        target = page.evaluate("() => window.__agentGraphViewer.cy.nodes()[0].renderedPosition()")
        assert canvas is not None
        page.mouse.move(canvas["x"] + target["x"], canvas["y"] + target["y"])
        expect(page.locator("#hover-card")).to_be_visible()
        expect(page.locator("#hover-card-title")).to_have_text("Hover target")
        after = page.evaluate(
            """() => window.__agentGraphViewer.cy.nodes().map(node => ({
              id: node.id(), position: node.position(), box: node.renderedBoundingBox({ includeLabels: true, includeOverlays: false }),
            }))"""
        )

    assert after_selection == before
    assert after == before
