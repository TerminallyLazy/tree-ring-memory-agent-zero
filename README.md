# Tree Ring Memory for Agent Zero

Plugin `3.3.1` targets the released Tree Ring `0.15` activation protocol and
requires Tree Ring `0.15.4` or a newer `0.15.x` patch. The published plugin
bundles verified `0.15.4` Linux executables for Agent Zero's x86-64 and ARM64
Docker runtimes.

This plugin is an Agent Zero bridge to the Rust-native Tree Ring Memory CLI. It
does not maintain a second Python memory engine.

The Rust CLI owns validation, sensitivity classification, SQLite/FTS storage, recall ranking, import/export, audit, consolidation, maintenance, DOX/Revolve adapters, coordinated write authorization, and integration discovery. The plugin owns Agent Zero context mapping, tools, API envelopes, Web UI shaping, safe host paths, runtime status, and guarded migration.

## Release and update boundary

- Plugin `3.3.1` supports `tree-ring` `0.15.4` through `0.15.x` and fails closed
  on older or different-minor executables.
- The checked-in `bin/` executables, provenance, and checksums are built from
  immutable core tag `v0.15.4` on native Linux runners in the pinned Debian
  Bookworm build image.
- The manual **Prepare Tree Ring 0.15.4 bundled binaries** workflow and
  [`scripts/stage-v0154-bundled-binaries.sh`](scripts/stage-v0154-bundled-binaries.sh)
  must be used together before any future bundled CLI replacement is published.

## Install and update

In Agent Zero open **Plugins → Install**, choose the Git repository option, and
use:

```text
https://github.com/TerminallyLazy/tree-ring-memory-agent-zero
```

The installer places the plugin under `usr/plugins/tree_ring_memory`. To update,
use the installed plugin's update action in Agent Zero, then restart the Agent
Zero runtime. The updated hooks validate the bundled CLI before opening the
configured Rust-owned store. Existing memory under
`usr/memory/tree_ring_memory` is preserved across updates and uninstall.
An unversioned v0.12 or versioned schema-v1/v2 Rust store waits for the explicit
offline schema-v3 workflow below.

A fresh install without a selected Agent Zero project waits for project
activation and does not initialize the legacy global memory root. Selecting a
project and choosing **Activate this project** creates or opens only that
project's `.tree-ring` store.

## Requirements

- Agent Zero with this directory mounted at `/a0/usr/plugins/tree_ring_memory/`.
- An executable `tree-ring` `0.15.x` binary. The plugin requires at least
  `0.15.4` and fails closed on other minor versions. Release builds bundle
  Linux binaries for Agent Zero's `x86_64` and `aarch64` Docker runtimes.
- Python 3.12+ in the Agent Zero framework runtime.

Binary discovery order is:

1. `TREE_RING_MEMORY_CLI` or `cli.binary`.
2. `/a0/usr/plugins/tree_ring_memory/bin/linux-<architecture>/tree-ring`.
3. `/a0/usr/plugins/tree_ring_memory/bin/tree-ring` for an operator-supplied generic fallback.
4. `<memory-root>/bin/tree-ring`.
5. `tree-ring` on the framework runtime `PATH`.

The install hook selects only the executable already packaged for the running
Docker architecture; it does not download or build executable code. Any
replacement binary remains an explicit operator action.

## Project activation protocol

Project activation is a proof flow, not a marker-file claim. Mount the project
read/write at Agent Zero's standard `/a0/usr/projects/<project>` path, choose
that project in **Plugin Settings**, and select **Activate this project**. The
plugin derives `activation.project_root` and the matching project-local
`storage.root`, saves the project-scoped configuration, and immediately runs
the existing core bootstrap command from the mounted project:

```text
tree-ring init --root .tree-ring --json
```

The plugin passes its fixed, installed, non-project
`activation-capability.json` only in that child process environment. Users do
not set its path, pass an environment variable, hand-write a binding, or use a
generic `.a0` marker. Core validates the descriptor and its sibling plugin
manifest; the plugin never writes the project binding itself.

Core creation-publishes an Agent Zero binding whose persisted state remains
`needs-plugin`, even while the installed plugin is present. Descriptor-scoped
runtime status may derive `configured-awaiting-proof` without changing that
passive record. When the selected project has a matching chat or task, the
activation action also runs preflight with that session-specific identity. If
no matching context exists yet, start or open a project chat to produce the
fresh project-local receipt that can make runtime status `active`.

The writer-context selector remains session-specific because attribution,
idempotency, coordinated writes, and activation receipts require a real chat or
task identity. The UI filters choices to the active project, displays compact
task/chat labels, and preserves the explicit selection across panel reopen and
page reload for the current browser session.

If the plugin is removed, a host CLI runs without the descriptor, or a second
agent points at a different store, status remains `needs-plugin` or
`active-isolated` as appropriate. Multiple Agent Zero workers can share the
same mounted `.tree-ring` root, but each receives its own receipt-backed proof;
the core store fingerprint and project binding prevent an arbitrary mount from
claiming that shared activation.

Installation alone is not activation proof. Only a fresh receipt-backed
preflight against the mounted project and matching store can report `active`.

## Storage

The default memory root remains:

```text
/a0/usr/memory/tree_ring_memory/
```

The current Rust-owned database is:

```text
/a0/usr/memory/tree_ring_memory/memory.sqlite
```

The Python-v1 database is preserved as read-only migration input:

```text
/a0/usr/memory/tree_ring_memory/indexes/memory.sqlite
```

Uninstall preserves both stores. Removing the memory root remains a deliberate operator action outside automatic plugin lifecycle handling.

## Schema-v3 upgrade introduced in v0.13

The `0.15` bridge never auto-opens an existing unversioned v0.12 or versioned
schema-v1/v2 store. The dashboard and settings report `upgrade_required` while
normal store operations remain blocked. The `pre-v0.13` wording in backup
filenames and markers is historical schema provenance, not a claim that a
v0.13 runtime is supported by plugin `3.3.1`.

Treat the upgrade as an offline, one-way operation:

1. Stop every Tree Ring CLI, plugin, TUI, and worker using the memory root.
2. In plugin settings, choose **Create verified upgrade backup** and attest that the root is offline.
3. The helper checkpoints and truncates SQLite WAL, acquires the database lock, verifies `PRAGMA integrity_check`, creates an exact mode-`0600` database backup under `<memory-root>/migrations/`, verifies SHA-256 and record count, and writes a mode-`0600` marker.
4. Choose **Apply schema v3** while every other process remains stopped. The plugin rechecks the source and backup checksums before allowing `tree-ring init` to migrate.
5. Upgrade every other CLI, plugin, and bundled worker before reopening the shared root.

If the source changes after backup, application fails closed and requires a fresh backup. Do not run v0.12 against an upgraded root. Schema v3 fences old memory inserts, updates, and deletes, but all mixed-version use—including reads and maintenance—is unsupported. Rollback means stopping every process and restoring the recorded complete backup; it is not a down-migration.

## Legacy Migration

Legacy Python-v1 migration never edits or deletes the old SQLite database. The migrator reads `raw_json`, normalizes Python-v1 null/string and `chat`-scope differences, writes a mode-`0600` temporary JSONL file, validates that file with `tree-ring import --dry-run`, and only then imports it through the Rust CLI. The temporary file is removed after the attempt.

Migration is idempotent. A marker under `<memory-root>/migrations/` prevents accidental repeats, while the Rust importer skips duplicate IDs by default. The original legacy database remains available as read-only recovery input. Automatic durable import occurs only while the Rust store policy is `open`; in `coordinated` mode the bridge performs only the dry-run preview until an authorized coordinator profile explicitly confirms migration.

## Multi-Agent and Coordinator Mapping

Every Agent Zero tool invocation derives its Tree Ring identity from the live server-side Agent Zero context:

- `agent_profile` comes from the active Agent Zero profile, with the Agent Zero name as a fallback.
- `project` comes from the active Agent Zero project.
- `session_id` is the current chat or worker context.
- `workflow_id` is the parent context for parallel fan-out workers and otherwise the current context.
- `operation_id` and `source_ref` are explicit tool inputs and are forwarded unchanged so a retry can reuse the same logical write identity and provenance.

The caller cannot set write identity through API payload fields. Recall can intentionally request a wider fan-in view with `include_all_agents=true`; that suppresses the current context's default agent/session filters while preserving any explicit agent, workflow, session, or scope filters.

Every subprocess starts from a copy of the host environment with `TREE_RING_COORDINATOR_TOKEN` and all Tree Ring identity environment variables removed. A coordinator capability is reinserted only when both conditions hold:

1. the operation is a protected mutation; and
2. the server-derived Agent Zero profile appears in `coordination.coordinator_profiles`.

The capability remains host-environment-only. It is not accepted by tools or API payloads, stored in plugin configuration, logged, returned, or rendered in the Web UI. Policy enable/rotate/disable and the one-time capability stay operator-only CLI actions. The plugin exposes only read-only `policy_status` and `policy_audit`.

Ordinary memories default to `scope=agent`, carry the derived identity, and do not receive the capability. In coordinated mode, shared/global/project/workflow writes, heartwood creation, evidence publication, persisted consolidation or adapter sync, imports, replacements, ring changes, delete/redact, and applied maintenance require coordinator authorization.

This is operational write authorization for cooperative official processes sharing one local SQLite store on one host. It is not a read ACL, an operating-system boundary, distributed coordination, or a cross-host/network-filesystem guarantee.

## Agent Tools

- `remember`: concise agent-scoped memory with server-derived identity plus optional `operation_id` and `source_ref`.
- `evidence`: evaluated outcomes with a required evidence reference.
- `recall`: Rust-ranked recall with native project/agent/workflow/session/scope filters and optional Agent Zero ring/event post-filters.
- `forget`: explicit-ID delete or redact.
- `consolidate`: daily, weekly, monthly, yearly, or manual consolidation.
- `audit_memory`: non-mutating quality, privacy, and integrity audit.
- `maintain_memory`: dry-run maintenance or explicit expiry/redaction/FTS repair.
- `sync_dox`: DOX source adapter; dry-run by default.
- `sync_revolve`: Revolve evidence adapter; dry-run by default.
- `import_memory`: dry-run by default, with optional duplicate replacement.
- `export_memory`: canonical JSONL export.
- `preflight`: produces the project-local, receipt-backed Agent Zero activation proof.
- `policy_status`: read-only coordinated-policy status.
- `policy_audit`: read-only protected-write authorization decisions.

The `0.15` CLI does not expose query-wide forget, selected-memory export,
Markdown/SQLite export, expiry, or supersession as scriptable commands. The
plugin returns an explicit unsupported-operation error for those former
Python-v1 surfaces.

## Web UI

The panel provides runtime/schema readiness, one-action project activation,
write-policy status, search, ring/event filters, memory detail, ring-derived
copies, delete/redact, consolidation, safe DOX/Revolve previews, memory and
policy audit, and canonical JSONL export. Its concentric Tree Ring visual
illuminates each ring relative to the busiest ring, while the adjacent ledger
shows exact record counts and share of the store; selecting a ring filters the
live results. A visible writer-context selector attributes protected actions to
an existing Agent Zero chat or task without weakening the server-side identity
gate. The settings view owns the explicit two-step schema upgrade, the
non-secret coordinator-profile allowlist, the selected-project configuration,
and compatibility hydration for partial configuration saved by older releases.

When the CLI is missing or incompatible, the panel stays available and shows the concrete readiness error instead of initializing a second store.

## Lifecycle and Maintenance

`hooks.py` owns automatic setup. Its install hook is idempotent, and Agent Zero
runs it after both fresh installs and updates. For a configured canonical
mounted project root, it asks the released core to create the passive binding
through the installed descriptor, then reloads that core-generated contract;
it never hand-writes or upgrades an activation binding. The configuration hook
provides a second idempotent bootstrap path after an update so older
installations cannot remain dependent on the removed `execute.py` script. An
unversioned v0.12 or versioned schema-v1/v2 preflight returns without opening
the database. Before later updates, the hook exports an initialized compatible
store as a recovery snapshot.

Interactive audit, consolidation, FTS repair, DOX/Revolve previews, import preview, and export remain available through the Web UI and Agent Zero tools. Sensitive recall and export remain opt-in. DOX `AGENTS.md`, Revolve evidence, current source, tests, and explicit user instructions remain authoritative over recalled memory.

## Verification

Focused package-layout tests use temporary roots and make no network calls:

```bash
PYTHONDONTWRITEBYTECODE=1 \
python3 -m pytest -q -p no:cacheprovider \
  tests/test_manifest.py tests/test_webui.py tests/test_activation_package_layout.py

node --check webui/memory-store.js
```

Upstream certification uses the exact released CLI in a real Agent Zero package
layout. The package tests also verify both bundled Linux binaries, immutable
provenance, checksums, activation envelopes, and the source-only bridge contract.

## Contribution Boundary

Keep implementation under `usr/plugins/tree_ring_memory/` and the companion guidance under `usr/skills/tree-ring-memory/`. Do not modify Agent Zero core code for this integration. If upstream changes its CLI or JSON schema, update the adapter and version gate together, then rerun the real CLI and legacy-copy proofs before changing the supported series.
