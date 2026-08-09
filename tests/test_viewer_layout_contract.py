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
from playwright.sync_api import Browser, Page, ViewportSize, expect, sync_playwright


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
        elif path.startswith("/api/cli/entity/"):
            entity_id = path.removeprefix("/api/cli/entity/")
            entity = next((node for node in server.nodes if node["id"] == entity_id), None)
            if entity:
                self._send(200, "application/json", entity)
            else:
                self._send(404, "application/json", {"detail": "not found"})
        elif path.startswith("/api/cli/edges/"):
            self._send(200, "application/json", server.edges)
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
          let minimumGap = Infinity;
          let totalNodeArea = 0;
          let x1 = Infinity;
          let y1 = Infinity;
          let x2 = -Infinity;
          let y2 = -Infinity;
          for (const { box } of boxes) {
            totalNodeArea += box.w * box.h;
            x1 = Math.min(x1, box.x1);
            y1 = Math.min(y1, box.y1);
            x2 = Math.max(x2, box.x2);
            y2 = Math.max(y2, box.y2);
          }
          for (let i = 0; i < boxes.length; i += 1) {
            for (let j = i + 1; j < boxes.length; j += 1) {
              const a = boxes[i].box;
              const b = boxes[j].box;
              if (a.x1 < b.x2 && a.x2 > b.x1 && a.y1 < b.y2 && a.y2 > b.y1) overlaps += 1;
              const horizontalGap = Math.max(a.x1 - b.x2, b.x1 - a.x2, 0);
              const verticalGap = Math.max(a.y1 - b.y2, b.y1 - a.y2, 0);
              minimumGap = Math.min(minimumGap, Math.hypot(horizontalGap, verticalGap));
            }
          }
          const graphArea = Math.max(x2 - x1, 1) * Math.max(y2 - y1, 1);
          return {
            overlaps,
            minimumGap,
            utilization: totalNodeArea / graphArea,
            insideViewport: boxes.every(({ box }) => (
              box.x1 >= 0 && box.y1 >= 0 && box.x2 <= cy.width() && box.y2 <= cy.height()
            )),
            boxes,
          };
        }"""
    )


def test_edge_free_graph_uses_a_non_overlapping_grid(page: Page) -> None:
    nodes = [_node(index, f"Isolated document {index}") for index in range(50)]
    with _serve_viewer(nodes, []) as url:
        _wait_for_graph(page, url, len(nodes))
        metrics = _layout_metrics(page)

    assert metrics["overlaps"] == 0
    assert metrics["minimumGap"] >= 16


def test_connected_long_label_graph_keeps_nodes_separate(page: Page) -> None:
    nodes = [
        _node(index, f"Long RSS article title {index}: " + "A detailed discussion of agent systems " * 3)
        for index in range(22)
    ]
    edges = [
        {
            "id": f"edge-{index}",
            "source_entity_id": "node-0",
            "target_entity_id": f"node-{index}",
            "edge_type": "contains",
        }
        for index in range(1, len(nodes))
    ]
    with _serve_viewer(nodes, edges) as url:
        _wait_for_graph(page, url, len(nodes))
        metrics = _layout_metrics(page)

    assert metrics["overlaps"] == 0
    assert metrics["minimumGap"] >= 16


@pytest.mark.parametrize("viewport", [{"width": 1280, "height": 720}, {"width": 800, "height": 900}])
def test_mixed_graph_packs_components_without_wasting_space(
    page: Page,
    viewport: ViewportSize,
) -> None:
    page.set_viewport_size(viewport)
    nodes = [_node(index, f"Mixed component document {index}") for index in range(10)]
    edges = [
        {
            "id": "edge-0-1",
            "source_entity_id": "node-0",
            "target_entity_id": "node-1",
            "edge_type": "contains",
        },
        {
            "id": "edge-1-2",
            "source_entity_id": "node-1",
            "target_entity_id": "node-2",
            "edge_type": "contains",
        },
        {
            "id": "edge-3-4",
            "source_entity_id": "node-3",
            "target_entity_id": "node-4",
            "edge_type": "contains",
        },
    ]
    with _serve_viewer(nodes, edges) as url:
        _wait_for_graph(page, url, len(nodes))
        metrics = _layout_metrics(page)

    assert metrics["overlaps"] == 0
    assert metrics["minimumGap"] >= 16
    assert metrics["insideViewport"] is True
    assert metrics["utilization"] >= 0.20


def test_page_title_includes_search_and_focused_node(page: Page) -> None:
    nodes = [_node(1, "Quarterly planning")]
    with _serve_viewer(nodes, []) as url:
        _wait_for_graph(page, f"{url}?search=roadmap&node_id=node-1", len(nodes))
        expect(page).to_have_title("AgentGraph Viewer | Search: roadmap | Focus: Quarterly planning")


def test_detail_panel_focus_button_focuses_the_displayed_entity(page: Page) -> None:
    nodes = [_node(1, "Focus target"), _node(2, "Neighbour")]
    with _serve_viewer(nodes, []) as url:
        _wait_for_graph(page, url, len(nodes))
        page.evaluate("() => window.__agentGraphViewer.cy.getElementById('node-1').emit('tap')")
        focus_button = page.locator("#detail-focus")
        expect(focus_button).to_be_visible()
        expect(focus_button).to_have_attribute("aria-label", "Focus on entity")
        expect(focus_button).to_have_attribute("aria-pressed", "false")

        focus_button.click()

        expect(page.locator("#lookup-input")).to_have_value("node-1")
        expect(page).to_have_url(f"{url}?node_id=node-1&selected_id=node-1")
        expect(page).to_have_title("AgentGraph Viewer | Focus: Focus target")
        expect(focus_button).to_have_attribute("aria-pressed", "true")


def test_slash_focuses_search_without_intercepting_text_input(page: Page) -> None:
    nodes = [_node(1, "Keyboard shortcuts")]
    with _serve_viewer(nodes, []) as url:
        _wait_for_graph(page, url, len(nodes))

        page.locator("#canvas-wrap").click(position={"x": 20, "y": 20})
        page.keyboard.press("/")
        expect(page.locator("#search-input")).to_be_focused()
        expect(page.locator("#search-input")).to_have_value("")

        lookup_input = page.locator("#lookup-input")
        lookup_input.focus()
        page.keyboard.type("/")
        expect(lookup_input).to_be_focused()
        expect(lookup_input).to_have_value("/")


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


def test_hover_card_hides_when_pointer_enters_detail_panel(page: Page) -> None:
    nodes = [_node(1, "Hover target")]
    with _serve_viewer(nodes, []) as url:
        _wait_for_graph(page, url, len(nodes))
        page.locator("#detail").evaluate("panel => panel.classList.add('open')")
        page.wait_for_timeout(250)
        canvas = page.locator("#cy").bounding_box()
        target = page.evaluate("() => window.__agentGraphViewer.cy.nodes()[0].renderedPosition()")
        detail = page.locator("#detail").bounding_box()
        assert canvas is not None
        assert detail is not None

        page.mouse.move(canvas["x"] + target["x"], canvas["y"] + target["y"])
        expect(page.locator("#hover-card")).to_be_visible()
        page.mouse.move(detail["x"] + 20, detail["y"] + 20)
        expect(page.locator("#hover-card")).not_to_be_visible()


def test_open_detail_uses_its_own_desktop_column(page: Page) -> None:
    nodes = [_node(1, "Detail target")]
    with _serve_viewer(nodes, []) as url:
        _wait_for_graph(page, url, len(nodes))
        canvas_before = page.locator("#canvas-wrap").bounding_box()
        page.locator("#app").evaluate("app => app.classList.add('detail-open')")
        page.locator("#detail").evaluate("panel => panel.classList.add('open')")
        page.wait_for_timeout(250)
        canvas_after = page.locator("#canvas-wrap").bounding_box()
        detail = page.locator("#detail").bounding_box()

    assert canvas_before is not None
    assert canvas_after is not None
    assert detail is not None
    assert canvas_before["width"] - canvas_after["width"] >= 300
    assert detail["x"] >= canvas_after["x"] + canvas_after["width"]
