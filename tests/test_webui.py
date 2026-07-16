from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ring_usage_visual_has_all_memory_types_and_live_bindings():
    html = (ROOT / "webui" / "main.html").read_text(encoding="utf-8")
    store = (ROOT / "webui" / "memory-store.js").read_text(encoding="utf-8")

    for ring in ("cambium", "outer", "inner", "heartwood", "scar", "seed"):
        assert f'data-ring="{ring}"' in html
    assert "ringArcStyle" in html
    assert "ringShareLabel" in html
    assert "ringUsagePercent" in store
    assert "maxRingCount" in store


def test_all_webui_launchers_target_the_discoverable_main_screen():
    config = (ROOT / "webui" / "config.html").read_text(encoding="utf-8")
    button = (ROOT / "webui" / "tree-ring-memory-button.html").read_text(encoding="utf-8")

    assert "/plugins/tree_ring_memory/webui/main.html" in config
    assert "/plugins/tree_ring_memory/webui/main.html" in button
    assert "/plugins/tree_ring_memory/webui/index.html" not in config + button
