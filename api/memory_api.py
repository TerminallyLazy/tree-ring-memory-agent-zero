from __future__ import annotations

from typing import Any

try:
    from helpers.api import ApiHandler, Request, Response
except ModuleNotFoundError:
    class ApiHandler:  # type: ignore[no-redef]
        pass

    Request = object  # type: ignore[assignment]
    Response = object  # type: ignore[assignment]

from usr.plugins.tree_ring_memory.helpers.cli import TreeRingCli, TreeRingCliError
from usr.plugins.tree_ring_memory.helpers.config import load_config
from usr.plugins.tree_ring_memory.helpers.legacy import LegacyMigrationError, LegacyMigrator
from usr.plugins.tree_ring_memory.helpers.values import parse_bool


def envelope(
    data: Any = None,
    *,
    ok: bool = True,
    warnings: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {"ok": ok, "data": {} if data is None else data, "warnings": warnings or [], "error": error}


class MemoryApi(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        del request
        action = str(input.get("action") or "search").strip().lower().replace("-", "_")
        config = load_config()
        bridge = TreeRingCli(config)
        try:
            if action == "status":
                status = bridge.status()
                return envelope(status, ok=bool(status.get("ok")), error=status.get("error"))
            if action == "search":
                data = bridge.recall(
                    str(input.get("query") or ""),
                    project=_optional_text(input.get("project")),
                    agent_profile=_optional_text(input.get("agent_profile")),
                    scope=_optional_text(input.get("scope")),
                    rings=_string_list(input.get("rings")) or None,
                    event_types=_string_list(input.get("event_types")) or None,
                    include_sensitive=parse_bool(input.get("include_sensitive"), False),
                    include_superseded=parse_bool(input.get("include_superseded"), False),
                    limit=int(input.get("limit") or (config.get("recall") or {}).get("max_results_default", 8)),
                    explain_ranking=parse_bool(input.get("explain_ranking"), False),
                )
                return envelope(data)
            if action == "remember":
                payload = dict(input.get("memory") or input)
                unsupported = _unsupported_remember_fields(payload)
                if unsupported:
                    return envelope(
                        ok=False,
                        error=(
                            "tree-ring 0.12 remember does not accept: "
                            + ", ".join(unsupported)
                            + ". Use the evidence action for evaluated details or store a concise summary."
                        ),
                    )
                event = bridge.remember(
                    str(payload.get("summary") or ""),
                    event_type=str(payload.get("event_type") or "lesson"),
                    ring=str(payload.get("ring") or "cambium"),
                    scope=str(payload.get("scope") or ("project" if payload.get("project") else "global")),
                    project=_optional_text(payload.get("project")),
                    tags=_string_list(payload.get("tags")),
                )
                return envelope({"memory_id": event.get("id"), "memory": event})
            if action == "evidence":
                event = bridge.evidence(
                    str(input.get("summary") or ""),
                    evidence_ref=str(input.get("evidence_ref") or ""),
                    outcome=str(input.get("outcome") or "observed"),
                    project=_optional_text(input.get("project")),
                    details=_optional_text(input.get("details")),
                    score=_optional_float(input.get("score")),
                    tags=_string_list(input.get("tags")),
                )
                return envelope({"memory_id": event.get("id"), "memory": event})
            if action == "memory":
                event = bridge.get_memory(
                    str(input.get("id") or input.get("memory_id") or ""),
                    include_sensitive=parse_bool(input.get("include_sensitive"), False),
                )
                if event is None:
                    return envelope(ok=False, error="Memory not found")
                return envelope(event)
            if action in {"rings", "stats"}:
                return envelope(bridge.stats())
            if action == "consolidate":
                return envelope(
                    bridge.consolidate(
                        period_type=str(input.get("period_type") or "daily"),
                        period_key=_optional_text(input.get("period_key")),
                        project=_optional_text(input.get("project")),
                        dry_run=parse_bool(input.get("dry_run"), False),
                        force=parse_bool(input.get("force"), False),
                    )
                )
            if action == "forget":
                memory_id = str(input.get("memory_id") or "")
                reason = str(input.get("reason") or "")
                if not memory_id:
                    return envelope(ok=False, error="memory_id is required; broad-query forget is not exposed by tree-ring 0.12")
                if not reason.strip():
                    return envelope(ok=False, error="reason is required")
                return envelope(
                    bridge.forget(memory_id, mode=str(input.get("mode") or "delete"), reason=reason)
                )
            if action == "audit":
                return envelope(bridge.audit(str(input.get("audit_type") or "all")))
            if action == "maintain":
                return envelope(
                    bridge.maintain(
                        project=_optional_text(input.get("project")),
                        include_superseded=parse_bool(input.get("include_superseded"), False),
                        apply_expired=parse_bool(input.get("apply_expired"), False),
                        apply_secret_redactions=parse_bool(input.get("apply_secret_redactions"), False),
                        repair_fts=parse_bool(input.get("repair_fts"), False),
                    )
                )
            if action == "sync_dox":
                return envelope(
                    bridge.sync_dox(
                        source_root=_optional_text(input.get("source_root") or input.get("root_path")),
                        project=_optional_text(input.get("project")),
                        dry_run=parse_bool(input.get("dry_run"), True),
                    )
                )
            if action == "sync_revolve":
                return envelope(
                    bridge.sync_revolve(
                        source_root=_optional_text(input.get("source_root") or input.get("revolve_root")),
                        project=_optional_text(input.get("project") or input.get("project_id")),
                        dry_run=parse_bool(input.get("dry_run"), True),
                    )
                )
            if action == "integrations":
                return envelope(
                    bridge.integrations_scan(source_root=_optional_text(input.get("source_root")))
                )
            if action == "export":
                if str(input.get("format") or "jsonl") != "jsonl":
                    return envelope(ok=False, error="tree-ring 0.12 exports canonical JSONL only")
                if input.get("memory_ids"):
                    return envelope(ok=False, error="tree-ring 0.12 does not expose selected-memory export")
                return envelope(
                    bridge.export_to_file(
                        output_path=_optional_text(input.get("output_path")),
                        include_sensitive=parse_bool(input.get("include_sensitive"), False),
                        include_superseded=parse_bool(input.get("include_superseded"), False),
                    )
                )
            if action == "import_preview":
                path = str(input.get("path") or "")
                if not path:
                    return envelope(ok=False, error="path is required")
                return envelope(bridge.import_file(path, dry_run=True))
            if action == "migrate":
                return envelope(
                    LegacyMigrator(config, cli=bridge).migrate(
                        confirm=parse_bool(input.get("confirm"), False),
                        force=parse_bool(input.get("force"), False),
                    )
                )
            if action == "rebuild_fts":
                return envelope(bridge.maintain(repair_fts=True))
            if action == "export_diagnostics":
                return envelope(
                    {
                        "status": bridge.status(),
                        "audit": bridge.audit("all"),
                        "export": bridge.export_to_file(),
                    }
                )
            return envelope(ok=False, error=f"Unknown action: {action}")
        except (TreeRingCliError, LegacyMigrationError, ValueError, OSError) as exc:
            return envelope(ok=False, error=str(exc))


def _unsupported_remember_fields(payload: dict[str, Any]) -> list[str]:
    unsupported = []
    for key in (
        "details",
        "source",
        "links",
        "salience",
        "confidence",
        "sensitivity",
        "retention",
        "expires_at",
        "supersedes",
        "superseded_by",
        "review",
    ):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            unsupported.append(key)
    return unsupported


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [value]
    return []
