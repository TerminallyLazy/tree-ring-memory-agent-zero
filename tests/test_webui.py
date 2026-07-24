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


def test_webui_forwards_context_and_exposes_only_safe_policy_reads():
    html = (ROOT / "webui" / "main.html").read_text(encoding="utf-8")
    config = (ROOT / "webui" / "config.html").read_text(encoding="utf-8")
    store = (ROOT / "webui" / "memory-store.js").read_text(encoding="utf-8")

    assert "currentContextId" in store
    assert "const contextId = currentContextId()" in store
    assert "context_id: contextId" in store
    assert "writerContextId" in store
    assert "writerContexts" in store
    assert "Choose a writer context or start a chat" in store
    assert 'aria-label="Tree Ring writer context"' in html
    assert 'aria-label="Tree Ring writer context"' in config
    assert 'post("policy_status")' in store
    assert 'post("policy_audit"' in store
    assert "policy enable" not in store.lower()
    assert "policy rotate" not in store.lower()
    assert "coordinator capability" not in html.lower()
    assert "one-time coordinator capability" in config.lower()
    assert "never exposed here" in config.lower()


def test_settings_hydrate_partial_legacy_config_before_alpine_binds_fields():
    config = (ROOT / "webui" / "config.html").read_text(encoding="utf-8")
    store = (ROOT / "webui" / "memory-store.js").read_text(encoding="utf-8")

    assert "hydrateSettingsConfig(config)" in config
    assert "mergeMissing(config, settingsDefaults)" in store
    assert "config.coordination?.coordinator_profiles" in config
    assert "(config.coordination ??= {}).coordinator_profiles" in config


def test_webui_shows_explicit_two_step_schema_upgrade_controls():
    config = (ROOT / "webui" / "config.html").read_text(encoding="utf-8")
    store = (ROOT / "webui" / "memory-store.js").read_text(encoding="utf-8")

    assert "prepare_schema_upgrade" in store
    assert "apply_schema_upgrade" in store
    assert "confirm_offline: true" in store
    assert "Create verified upgrade backup" in config
    assert "Apply schema v3" in config
    assert "unversioned v0.12 or versioned schema-v1/v2" in config
