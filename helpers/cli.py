from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from usr.plugins.tree_ring_memory.helpers import paths, upgrade
from usr.plugins.tree_ring_memory.helpers.config import load_config
from usr.plugins.tree_ring_memory.helpers.context import (
    InvocationContext,
    coordinator_profiles,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
VERSION_RE = re.compile(r"\btree-ring\s+(\d+)\.(\d+)\.(\d+)(?:[-+][^\s]+)?")
COORDINATOR_TOKEN_ENV = "TREE_RING_COORDINATOR_TOKEN"
IDENTITY_ENV_VARS = (
    COORDINATOR_TOKEN_ENV,
    "TREE_RING_AGENT_PROFILE",
    "TREE_RING_WORKFLOW_ID",
    "TREE_RING_SESSION_ID",
    "TREE_RING_OPERATION_ID",
)
CAPABILITY_RE = re.compile(r"trcap_v1_[a-f0-9]{64}", re.IGNORECASE)


class TreeRingCliError(RuntimeError):
    pass


class TreeRingCli:
    """Version-pinned adapter for the Rust-native Tree Ring Memory CLI.

    This class owns no memory schema or ranking behavior. All durable reads and
    writes cross the public ``tree-ring`` command surface.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        context: InvocationContext | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.config = load_config(config)
        self.root = paths.memory_root(self.config)
        self.context = context or InvocationContext()
        self.runner = runner or subprocess.run
        self._binary: Path | None = None
        self._version: str | None = None

    @property
    def required_version(self) -> str:
        return str((self.config.get("cli") or {}).get("required_version") or "0.13.0")

    @property
    def binary(self) -> Path:
        if self._binary is None:
            self._binary = self._resolve_binary()
        return self._binary

    @property
    def version(self) -> str:
        if self._version is None:
            result = self._run_process([str(self.binary), "--version"], include_cwd=False)
            match = VERSION_RE.search(result.stdout.strip())
            if not match:
                raise TreeRingCliError("Unable to parse the installed tree-ring version.")
            found = ".".join(match.groups())
            self._assert_compatible(found)
            self._version = found
        return self._version

    def status(self) -> dict[str, Any]:
        legacy = paths.legacy_sqlite_path(self.config)
        marker = paths.migration_marker_path(self.config)
        data: dict[str, Any] = {
            "ok": False,
            "runtime_ok": False,
            "required_version": self.required_version,
            "root": str(self.root),
            "sqlite_path": str(paths.canonical_sqlite_path(self.config)),
            "legacy_sqlite_path": str(legacy),
            "legacy_store_present": legacy.is_file(),
            "legacy_migration_pending": legacy.is_file() and not marker.is_file(),
        }
        try:
            preflight = upgrade.inspect_store(self.config)
            data.update(preflight)
            data["initialized"] = bool(
                preflight.get("present") and preflight.get("schema_version")
            )
        except upgrade.SchemaUpgradeError as exc:
            data["initialized"] = False
            data["error"] = str(exc)
            return data

        try:
            data.update(
                {
                    "binary": str(self.binary),
                    "version": self.version,
                    "runtime_ok": True,
                }
            )
        except TreeRingCliError as exc:
            data["error"] = str(exc)
            return data

        if data.get("unsupported_schema"):
            data["error"] = (
                f"Tree Ring SQLite schema {data.get('schema_version')} is newer than "
                f"the supported schema {upgrade.TARGET_SCHEMA_VERSION}."
            )
        elif data.get("upgrade_required"):
            prepared = " A verified backup is ready." if data.get("upgrade_prepared") else ""
            data["error"] = (
                f"Schema-v3 upgrade required for the existing schema-v{data.get('schema_version')} "
                "store. Stop every Tree Ring process, create a verified backup, then apply the "
                f"upgrade.{prepared}"
            )
        else:
            data["ok"] = True
        return data

    def init(self) -> dict[str, Any]:
        paths.ensure_memory_dirs(self.config)
        inspection = upgrade.inspect_store(self.config)
        migrating = bool(inspection.get("upgrade_required"))
        if migrating:
            upgrade.verify_prepared_upgrade(self.config)
        result = _require_dict(self._run_json(["init"]), "init")
        final = upgrade.inspect_store(self.config)
        if final.get("schema_version") != upgrade.TARGET_SCHEMA_VERSION:
            raise TreeRingCliError(
                f"tree-ring init did not produce SQLite schema {upgrade.TARGET_SCHEMA_VERSION}."
            )
        if migrating:
            upgrade.mark_upgrade_completed(self.config, cli_version=self.version)
        return result

    def prepare_schema_upgrade(self, *, confirm_offline: bool) -> dict[str, Any]:
        _ = self.version
        return upgrade.prepare_schema_upgrade(
            self.config, confirm_offline=confirm_offline
        )

    def apply_schema_upgrade(self, *, confirm_offline: bool) -> dict[str, Any]:
        if not confirm_offline:
            raise TreeRingCliError(
                "Explicit offline confirmation is required before applying schema v3."
            )
        upgrade.verify_prepared_upgrade(self.config)
        result = self.init()
        audit = self.audit("all")
        return {
            "ok": True,
            "init": result,
            "audit": audit,
            "status": self.status(),
            "message": "The verified store backup was preserved and schema v3 is active.",
        }

    def ensure_initialized(self) -> None:
        inspection = upgrade.inspect_store(self.config)
        if inspection.get("unsupported_schema"):
            raise TreeRingCliError(
                f"Tree Ring SQLite schema {inspection.get('schema_version')} is newer "
                f"than supported schema {upgrade.TARGET_SCHEMA_VERSION}."
            )
        if inspection.get("upgrade_required"):
            raise TreeRingCliError(
                f"Schema-v3 upgrade required for the existing schema-v{inspection.get('schema_version')} "
                "store. Stop every Tree Ring process, create a verified backup, and explicitly "
                "apply the upgrade before using this store."
            )
        if not inspection.get("present") or not inspection.get("schema_version"):
            self.init()

    def remember(
        self,
        summary: str,
        *,
        event_type: str,
        ring: str = "cambium",
        scope: str = "agent",
        project: str | None = None,
        operation_id: str | None = None,
        source_ref: str | None = None,
        tags: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        self.ensure_initialized()
        args = [
            "remember",
            summary,
            "--event-type",
            event_type,
            "--ring",
            ring,
            "--scope",
            scope,
        ]
        args.extend(self._identity_args(project=project))
        if operation_id:
            args.extend(["--operation-id", operation_id])
        if source_ref:
            args.extend(["--source-ref", source_ref])
        for tag in tags or ():
            if str(tag).strip():
                args.extend(["--tag", str(tag).strip()])
        protected = (
            ring.strip().lower() == "heartwood"
            or scope.strip().lower() != "agent"
            or not self.context.agent_profile
        )
        payload = self._run_json(args, protected=protected)
        return _require_dict(payload, "remember")

    def evidence(
        self,
        summary: str,
        *,
        evidence_ref: str,
        outcome: str = "observed",
        project: str | None = None,
        operation_id: str | None = None,
        details: str | None = None,
        score: float | None = None,
        tags: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        self.ensure_initialized()
        args = ["evidence", summary, "--outcome", outcome, "--evidence-ref", evidence_ref]
        args.extend(self._identity_args(project=project))
        if operation_id:
            args.extend(["--operation-id", operation_id])
        if details:
            args.extend(["--details", details])
        if score is not None:
            args.extend(["--score", str(float(score))])
        for tag in tags or ():
            if str(tag).strip():
                args.extend(["--tag", str(tag).strip()])
        return _require_dict(self._run_json(args, protected=True), "evidence")

    def recall(
        self,
        query: str,
        *,
        project: str | None = None,
        agent_profile: str | None = None,
        workflow_id: str | None = None,
        session_id: str | None = None,
        include_all_agents: bool = False,
        scope: str | None = None,
        rings: list[str] | None = None,
        event_types: list[str] | None = None,
        include_sensitive: bool = False,
        include_superseded: bool = False,
        limit: int | None = None,
        explain_ranking: bool = False,
    ) -> dict[str, Any]:
        if include_superseded:
            raise TreeRingCliError("tree-ring 0.13 recall does not expose superseded memories.")
        self.ensure_initialized()
        requested_limit = max(
            1,
            min(
                100,
                int(
                    limit
                    or (self.config.get("recall") or {}).get(
                        "max_results_default", 8
                    )
                ),
            ),
        )
        effective_project = project or self.context.project
        effective_agent = (
            None
            if include_all_agents
            else (agent_profile or self.context.agent_profile)
        )
        effective_workflow = workflow_id or self.context.workflow_id
        effective_session = (
            None
            if include_all_agents
            else (session_id or self.context.session_id)
        )
        if not query.strip():
            memories = self.list_memories(include_sensitive=include_sensitive, include_superseded=False)
            results = self._filter_memories(
                memories,
                project=effective_project,
                agent_profile=effective_agent,
                workflow_id=effective_workflow,
                session_id=effective_session,
                scope=scope,
                rings=rings,
                event_types=event_types,
            )[:requested_limit]
            return {
                "query": query,
                "count": len(results),
                "results": [{**item, "score": None} for item in results],
            }

        scan_limit = max(
            requested_limit * 5,
            int((self.config.get("recall") or {}).get("bridge_scan_limit", 100)),
        )
        args = ["recall", query, "--limit", str(min(1000, scan_limit))]
        if effective_project:
            args.extend(["--project", effective_project])
        if effective_agent:
            args.extend(["--agent-profile", effective_agent])
        if effective_workflow:
            args.extend(["--workflow-id", effective_workflow])
        if effective_session:
            args.extend(["--session-id", effective_session])
        if scope:
            args.extend(["--scope", scope])
        if include_sensitive:
            args.append("--include-sensitive")
        payload = self._run_json(args)
        if not isinstance(payload, list):
            raise TreeRingCliError("tree-ring recall returned an unexpected JSON shape.")
        flattened: list[dict[str, Any]] = []
        for entry in payload:
            if not isinstance(entry, dict) or not isinstance(entry.get("memory"), dict):
                continue
            memory = dict(entry["memory"])
            memory["score"] = entry.get("score")
            if explain_ranking:
                memory["ranking"] = entry.get("ranking") or {}
            flattened.append(memory)
        filtered = self._filter_memories(
            flattened,
            project=effective_project,
            agent_profile=effective_agent,
            workflow_id=effective_workflow,
            session_id=effective_session,
            scope=scope,
            rings=rings,
            event_types=event_types,
        )[:requested_limit]
        return {"query": query, "count": len(filtered), "results": filtered}

    def get_memory(self, memory_id: str, *, include_sensitive: bool = False) -> dict[str, Any] | None:
        for memory in self.list_memories(include_sensitive=include_sensitive, include_superseded=True):
            if memory.get("id") == memory_id:
                return memory
        return None

    def list_memories(
        self, *, include_sensitive: bool = False, include_superseded: bool = False
    ) -> list[dict[str, Any]]:
        self.ensure_initialized()
        args = ["export"]
        if include_sensitive:
            args.append("--include-sensitive")
        if include_superseded:
            args.append("--include-superseded")
        output = self._invoke(args).stdout
        memories: list[dict[str, Any]] = []
        for line_number, line in enumerate(output.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TreeRingCliError(f"tree-ring export returned invalid JSONL at line {line_number}.") from exc
            record = self._redact_payload(record)
            if record.get("type") == "memory_event" and isinstance(record.get("memory"), dict):
                memories.append(record["memory"])
        return memories

    def stats(self) -> dict[str, Any]:
        memories = self.list_memories(include_sensitive=False, include_superseded=False)
        counts = {ring: 0 for ring in ("cambium", "outer", "inner", "heartwood", "scar", "seed")}
        for memory in memories:
            ring = str(memory.get("ring") or "")
            if ring in counts:
                counts[ring] += 1
        return {
            "counts": counts,
            "total": len(memories),
            "last_consolidation": None,
            "cli_version": self.version,
        }

    def forget(self, memory_id: str, *, mode: str, reason: str) -> dict[str, Any]:
        self.ensure_initialized()
        if mode not in {"delete", "redact"}:
            raise TreeRingCliError("tree-ring 0.13 forget supports only delete or redact.")
        return _require_dict(
            self._run_json(
                ["forget", memory_id, "--mode", mode, "--reason", reason],
                protected=True,
            ),
            "forget",
        )

    def audit(self, audit_type: str = "all") -> dict[str, Any]:
        self._require_existing_schema_v3()
        return _require_dict(self._run_json(["audit", "--audit-type", audit_type]), "audit")

    def policy_status(self) -> dict[str, Any]:
        self._require_existing_schema_v3()
        return _require_dict(self._run_json(["policy", "status"]), "policy status")

    def policy_audit(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self._require_existing_schema_v3()
        parsed_limit = int(limit)
        if not 1 <= parsed_limit <= 1000:
            raise TreeRingCliError("Policy audit limit must be between 1 and 1000.")
        payload = self._run_json(
            ["policy", "audit", "--limit", str(parsed_limit)]
        )
        if not isinstance(payload, list):
            raise TreeRingCliError(
                "tree-ring policy audit returned an unexpected JSON shape."
            )
        return [entry for entry in payload if isinstance(entry, dict)]

    def _require_existing_schema_v3(self) -> None:
        inspection = upgrade.inspect_store(self.config)
        version = inspection.get("schema_version")
        if not inspection.get("present"):
            raise TreeRingCliError(
                "The Tree Ring store is not initialized; this read-only operation will not create it."
            )
        if inspection.get("unsupported_schema"):
            raise TreeRingCliError(
                f"Tree Ring SQLite schema {version} is newer than supported schema "
                f"{upgrade.TARGET_SCHEMA_VERSION}."
            )
        if version != upgrade.TARGET_SCHEMA_VERSION:
            raise TreeRingCliError(
                f"Schema-v3 upgrade required for the existing schema-v{version} store. "
                "This read-only operation will not initialize or migrate it."
            )

    def consolidate(
        self,
        *,
        period_type: str = "daily",
        period_key: str | None = None,
        project: str | None = None,
        agent_profile: str | None = None,
        workflow_id: str | None = None,
        session_id: str | None = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        self.ensure_initialized()
        args = ["consolidate", "--period-type", period_type]
        if period_key:
            args.extend(["--period-key", period_key])
        effective_project = project or self.context.project
        effective_agent = agent_profile or self.context.agent_profile
        effective_workflow = workflow_id or self.context.workflow_id
        effective_session = session_id or self.context.session_id
        if effective_project:
            args.extend(["--project", effective_project])
        if effective_agent:
            args.extend(["--agent-profile", effective_agent])
        if effective_workflow:
            args.extend(["--workflow-id", effective_workflow])
        if effective_session:
            args.extend(["--session-id", effective_session])
        if dry_run:
            args.append("--dry-run")
        if force:
            args.append("--force")
        return _require_dict(
            self._run_json(args, protected=not dry_run), "consolidate"
        )

    def maintain(
        self,
        *,
        project: str | None = None,
        include_superseded: bool = False,
        apply_expired: bool = False,
        apply_secret_redactions: bool = False,
        repair_fts: bool = False,
    ) -> dict[str, Any]:
        self.ensure_initialized()
        args = ["maintain"]
        effective_project = project or self.context.project
        if effective_project:
            args.extend(["--project", effective_project])
        if include_superseded:
            args.append("--include-superseded")
        if apply_expired:
            args.append("--apply-expired")
        if apply_secret_redactions:
            args.append("--apply-secret-redactions")
        if repair_fts:
            args.append("--repair-fts")
        protected = apply_expired or apply_secret_redactions or repair_fts
        return _require_dict(
            self._run_json(args, protected=protected), "maintain"
        )

    def export_to_file(
        self,
        *,
        output_path: str | None = None,
        include_sensitive: bool = False,
        include_superseded: bool = False,
    ) -> dict[str, Any]:
        self.ensure_initialized()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = paths.safe_output_path(
            self.config, output_path, f"tree-ring-memory-{stamp}.jsonl"
        )
        args = ["export", "--output", str(output)]
        if include_sensitive:
            args.append("--include-sensitive")
        if include_superseded:
            args.append("--include-superseded")
        return _require_dict(self._run_json(args), "export")

    def import_file(
        self, path: str, *, dry_run: bool = True, replace_existing: bool = False
    ) -> dict[str, Any]:
        source = paths.safe_import_path(self.config, path)
        return self._import_path(source, dry_run=dry_run, replace_existing=replace_existing)

    def import_trusted_migration_file(
        self, path: Path, *, dry_run: bool, replace_existing: bool = False
    ) -> dict[str, Any]:
        source = paths.trusted_migration_path(self.config, path)
        return self._import_path(source, dry_run=dry_run, replace_existing=replace_existing)

    def sync_dox(
        self, *, source_root: str | None = None, project: str | None = None, dry_run: bool = False
    ) -> dict[str, Any]:
        self.ensure_initialized()
        source = paths.safe_project_root(self.config, source_root)
        args = ["dox", "sync", "--source-root", str(source)]
        effective_project = project or self.context.project
        if effective_project:
            args.extend(["--project", effective_project])
        if dry_run:
            args.append("--dry-run")
        return _require_dict(
            self._run_json(args, protected=not dry_run), "dox sync"
        )

    def sync_revolve(
        self, *, source_root: str | None = None, project: str | None = None, dry_run: bool = False
    ) -> dict[str, Any]:
        self.ensure_initialized()
        source = paths.safe_project_root(self.config, source_root or "revolve")
        args = ["revolve", "sync", "--source-root", str(source)]
        effective_project = project or self.context.project
        if effective_project:
            args.extend(["--project", effective_project])
        if dry_run:
            args.append("--dry-run")
        return _require_dict(
            self._run_json(args, protected=not dry_run), "revolve sync"
        )

    def integrations_scan(self, *, source_root: str | None = None) -> dict[str, Any]:
        source = paths.safe_project_root(self.config, source_root)
        return _require_dict(
            self._run_json(["integrations", "scan", "--source-root", str(source)]),
            "integrations scan",
        )

    def _import_path(self, source: Path, *, dry_run: bool, replace_existing: bool) -> dict[str, Any]:
        if not dry_run:
            self.ensure_initialized()
        args = ["import", str(source)]
        if dry_run:
            args.append("--dry-run")
        if replace_existing:
            args.append("--replace-existing")
        return _require_dict(
            self._run_json(args, protected=not dry_run), "import"
        )

    def _filter_memories(
        self,
        memories: list[dict[str, Any]],
        *,
        project: str | None,
        agent_profile: str | None,
        workflow_id: str | None,
        session_id: str | None,
        scope: str | None,
        rings: list[str] | None,
        event_types: list[str] | None,
    ) -> list[dict[str, Any]]:
        results = []
        for memory in memories:
            if project and memory.get("project") != project:
                continue
            if agent_profile and memory.get("agent_profile") != agent_profile:
                continue
            if workflow_id and memory.get("workflow_id") != workflow_id:
                continue
            if session_id and memory.get("session_id") != session_id:
                continue
            if scope and memory.get("scope") != scope:
                continue
            if rings and memory.get("ring") not in rings:
                continue
            if event_types and memory.get("event_type") not in event_types:
                continue
            results.append(memory)
        return results

    def _identity_args(self, *, project: str | None) -> list[str]:
        args: list[str] = []
        effective_project = self._bound_write_project(project)
        if effective_project:
            args.extend(["--project", effective_project])
        if self.context.agent_profile:
            args.extend(["--agent-profile", self.context.agent_profile])
        if self.context.workflow_id:
            args.extend(["--workflow-id", self.context.workflow_id])
        if self.context.session_id:
            args.extend(["--session-id", self.context.session_id])
        return args

    def _bound_write_project(self, project: str | None) -> str | None:
        requested = project.strip() if project else None
        active = self.context.project
        if active and requested and requested != active:
            raise TreeRingCliError(
                "Write project must match the active Agent Zero project context."
            )
        return active or requested

    def _run_json(self, args: list[str], *, protected: bool = False) -> Any:
        output = self._invoke(args, protected=protected).stdout.strip()
        try:
            return self._redact_payload(json.loads(output))
        except json.JSONDecodeError as exc:
            raise TreeRingCliError("tree-ring returned invalid JSON for a scriptable command.") from exc

    def _invoke(
        self, args: list[str], *, protected: bool = False
    ) -> subprocess.CompletedProcess[str]:
        # Reject capability material before even probing the binary version.
        # This keeps an untrusted field from ever entering a process argv.
        self._assert_no_capability_arguments(args)
        _ = self.version
        command = [str(self.binary), "--root", str(self.root), "--json", *args]
        return self._run_process(
            command, include_cwd=True, protected=protected
        )

    def _run_process(
        self,
        command: list[str],
        *,
        include_cwd: bool,
        protected: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        # Defense in depth for every subprocess call, including version probes.
        self._assert_no_capability_arguments(command)
        timeout = int((self.config.get("cli") or {}).get("timeout_seconds", 30))
        try:
            result = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                cwd=str(paths.REPO_ROOT) if include_cwd else None,
                env=self._process_environment(protected=protected),
            )
        except FileNotFoundError as exc:
            raise TreeRingCliError("tree-ring is not installed for the Agent Zero framework runtime.") from exc
        except subprocess.TimeoutExpired as exc:
            raise TreeRingCliError(f"tree-ring command timed out after {timeout} seconds.") from exc
        except OSError as exc:
            raise TreeRingCliError(f"tree-ring could not start: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or "tree-ring command failed").strip().splitlines()[0][:500]
            raise TreeRingCliError(self._redact_capability(detail))
        return result

    def _assert_no_capability_arguments(self, arguments: Iterable[str]) -> None:
        host_capability = os.environ.get(COORDINATOR_TOKEN_ENV)
        for argument in arguments:
            value = str(argument)
            if CAPABILITY_RE.search(value) or (
                host_capability and host_capability in value
            ):
                raise TreeRingCliError(
                    "Coordinator capability material is not accepted in Tree Ring command arguments."
                )

    def _process_environment(self, *, protected: bool) -> dict[str, str]:
        environment = dict(os.environ)
        for name in IDENTITY_ENV_VARS:
            environment.pop(name, None)

        if (
            protected
            and self.context.agent_profile
            and self.context.agent_profile in coordinator_profiles(self.config)
        ):
            capability = os.environ.get(COORDINATOR_TOKEN_ENV)
            if capability and capability.strip():
                environment[COORDINATOR_TOKEN_ENV] = capability
        return environment

    def _redact_capability(self, value: str) -> str:
        redacted = CAPABILITY_RE.sub("[REDACTED]", value)
        capability = os.environ.get(COORDINATOR_TOKEN_ENV)
        if capability:
            redacted = redacted.replace(capability, "[REDACTED]")
        return redacted

    def _redact_payload(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_capability(value)
        if isinstance(value, list):
            return [self._redact_payload(item) for item in value]
        if isinstance(value, dict):
            return {
                key: self._redact_payload(item)
                for key, item in value.items()
                if str(key).lower()
                not in {"capability", "coordinator_token", "tree_ring_coordinator_token"}
            }
        return value

    def _resolve_binary(self) -> Path:
        configured = str((self.config.get("cli") or {}).get("binary") or "tree-ring")
        candidates: list[Path] = []
        if os.sep in configured or (os.altsep and os.altsep in configured):
            candidates.append(Path(configured).expanduser())
        else:
            resolved = shutil.which(configured)
            if resolved:
                candidates.append(Path(resolved))
        platform_target = _bundled_platform_target()
        if platform_target:
            candidates.append(paths.plugin_path("bin", platform_target, "tree-ring"))
        candidates.extend(
            [
                paths.plugin_path("bin", "tree-ring"),
                self.root / "bin" / "tree-ring",
            ]
        )
        fallback = shutil.which("tree-ring")
        if fallback:
            candidates.append(Path(fallback))
        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if resolved.is_file() and os.access(resolved, os.X_OK):
                return resolved
        raise TreeRingCliError(
            "tree-ring is not installed for this runtime. Configure cli.binary or place a v0.13.x "
            "binary in the plugin bin directory."
        )

    def _assert_compatible(self, found: str) -> None:
        required_tuple = _version_tuple(self.required_version)
        found_tuple = _version_tuple(found)
        if found_tuple[:2] != required_tuple[:2] or found_tuple < required_tuple:
            raise TreeRingCliError(
                f"Unsupported tree-ring version {found}; this plugin requires "
                f"{self.required_version} through {required_tuple[0]}.{required_tuple[1]}.x."
            )


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise TreeRingCliError(f"Invalid configured tree-ring version: {value}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _bundled_platform_target() -> str | None:
    """Return the packaged Docker target for the current runtime, if supported."""

    if platform.system().lower() != "linux":
        return None
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64"}:
        return "linux-aarch64"
    if machine in {"x86_64", "amd64"}:
        return "linux-x86_64"
    return None


def _require_dict(payload: Any, command: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TreeRingCliError(f"tree-ring {command} returned an unexpected JSON shape.")
    return payload
