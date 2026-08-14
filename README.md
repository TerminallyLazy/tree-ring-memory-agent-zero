# Tree Ring Memory for Agent Zero

> Pending compatibility branch: plugin `3.1.0` targets the Tree Ring `0.14`
> activation protocol. It is **not released or installable yet**. The immutable
> core `v0.14.0` tag and matching native Linux artifacts do not exist on this
> branch, so no live activation claim is warranted.

This plugin is an Agent Zero bridge to the Rust-native Tree Ring Memory CLI. It
does not maintain a second Python memory engine.

The Rust CLI owns validation, sensitivity classification, SQLite/FTS storage, recall ranking, import/export, audit, consolidation, maintenance, DOX/Revolve adapters, coordinated write authorization, and integration discovery. The plugin owns Agent Zero context mapping, tools, API envelopes, Web UI shaping, safe host paths, runtime status, and guarded migration.

## Release boundary

This source branch deliberately carries a future metadata/configuration contract
ahead of its distributable runtime:

- Plugin `3.1.0` requires `tree-ring` `0.14.x`.
- The checked-in `bin/` files, their provenance, checksums, and the binary
  workflow are still the released `v0.13.0` artifacts. They are historical
  evidence only and **must not** be republished, installed, or represented as
  `0.14` binaries.
- A release requires the immutable core `v0.14.0` tag plus matching native
  Linux artifacts, checksums, and provenance. Only then may this plugin be
  installed or published as a compatible release.

### Release handoff

Once the core tag has been created, run the plugin's manual **Prepare Tree Ring
0.14 bundled binaries** workflow. Download both architecture artifacts from
the same successful run and stage them with
[`scripts/stage-v014-bundled-binaries.sh`](scripts/stage-v014-bundled-binaries.sh).
That command verifies the artifacts' per-architecture checksums, immutable tag
provenance, resolved source commit, native runner/machine, pinned build image,
and CLI version before it can replace `bin/`. Then run the real-core test suite
with the released executable, review the complete `bin/` diff, change this
pending-release wording, and only then create the plugin's `3.1.0` release.

## Install after release

After the compatible release artifacts exist, in Agent Zero open **Plugins →
Install**, choose the Git repository option, and use:

```text
https://github.com/TerminallyLazy/tree-ring-memory-agent-zero
```

The installer places the plugin under `usr/plugins/tree_ring_memory`. Its hooks
validate the released CLI and initialize only the configured Rust-owned store.
Existing memory under `usr/memory/tree_ring_memory` is preserved across updates
and uninstall. An unversioned v0.12 or versioned schema-v1/v2 Rust store waits
for the explicit offline schema-v3 workflow below.

## Requirements after release

- Agent Zero with this directory mounted at `/a0/usr/plugins/tree_ring_memory/`.
- An executable `tree-ring` `0.14.x` binary. The plugin requires at least
  `0.14.0` and fails closed on other minor versions. Release builds bundle
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

## Project activation protocol after release

Project activation is a proof flow, not a marker-file claim. The user configures
only two matching in-runtime paths:

1. Mount the project read/write into Agent Zero and set
   `activation.project_root` to that mounted project directory.
2. Set `storage.root` to exactly
   `<activation.project_root>/.tree-ring` and save the plugin settings.

When those paths are canonical and reachable, the plugin bootstrap invokes the
existing core command from the mounted project:

```text
tree-ring --root .tree-ring --json init
```

The plugin passes its fixed, installed, non-project
`activation-capability.json` only in that child process environment. Users do
not set its path, pass an environment variable, hand-write a binding, or use a
generic `.a0` marker. Core validates the descriptor and its sibling plugin
manifest; the plugin never writes the project binding itself.

Core creation-publishes an Agent Zero binding whose persisted state remains
`needs-plugin`, even while the installed plugin is present. Descriptor-scoped
runtime status may derive `configured-awaiting-proof` without changing that
passive record. In a new Agent Zero session, choose a writer context and run
the `preflight` tool. Only its server-derived identity and a fresh matching
project-local receipt can make runtime status `active`.

If the plugin is removed, a host CLI runs without the descriptor, or a second
agent points at a different store, status remains `needs-plugin` or
`active-isolated` as appropriate. Multiple Agent Zero workers can share the
same mounted `.tree-ring` root, but each receives its own receipt-backed proof;
the core store fingerprint and project binding prevent an arbitrary mount from
claiming that shared activation.

This protocol is pending until the release boundary above is satisfied. Do not
use the current branch to claim that a running Agent Zero instance is active.

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

The `0.14` bridge never auto-opens an existing unversioned v0.12 or versioned
schema-v1/v2 store. The dashboard and settings report `upgrade_required` while
normal store operations remain blocked. The `pre-v0.13` wording in backup
filenames and markers is historical schema provenance, not a claim that a
v0.13 runtime is supported by plugin `3.1.0`.

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

The `0.14` CLI does not expose query-wide forget, selected-memory export,
Markdown/SQLite export, expiry, or supersession as scriptable commands. The
plugin returns an explicit unsupported-operation error for those former
Python-v1 surfaces.

## Web UI

![Tree Ring Memory dashboard](screenshots/tree-ring-memory-dashboard.png)

The panel provides runtime/schema readiness, project activation status,
write-policy status, search, ring/event filters, memory detail, ring-derived
copies, delete/redact, consolidation, safe DOX/Revolve previews, memory and
policy audit, and canonical JSONL export. Its concentric Tree Ring visual
illuminates each ring relative to the busiest ring, while the adjacent ledger
shows exact record counts and share of the store; selecting a ring filters the
live results. A visible writer-context selector attributes protected actions to
an existing Agent Zero chat or task without weakening the server-side identity
gate. The settings view owns the explicit two-step schema upgrade, the
non-secret coordinator-profile allowlist, the mounted-project configuration,
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

After the core release exists, upstream certification must use the exact released
`target/release/tree-ring` artifact in a real Agent Zero package layout. Until
then, this repository has no real CLI activation proof.

## Contribution Boundary

Keep implementation under `usr/plugins/tree_ring_memory/` and the companion guidance under `usr/skills/tree-ring-memory/`. Do not modify Agent Zero core code for this integration. If upstream changes its CLI or JSON schema, update the adapter and version gate together, then rerun the real CLI and legacy-copy proofs before changing the supported series.
