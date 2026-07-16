# Tree Ring Memory for Agent Zero

This plugin is an Agent Zero bridge to the Rust-native Tree Ring Memory CLI. Version 2.0 targets the upstream `tree-ring` 0.12 command and JSON contracts; it does not maintain a second Python memory engine.

The Rust CLI owns validation, sensitivity classification, SQLite/FTS storage, recall ranking, import/export, audit, consolidation, maintenance, DOX/Revolve adapters, and integration discovery. The plugin owns only Agent Zero tools, API envelopes, Web UI shaping, safe host paths, runtime status, and legacy migration.

## Install

In Agent Zero, open **Plugins → Install**, choose the Git repository option, and use:

```text
https://github.com/TerminallyLazy/tree-ring-memory-agent-zero
```

The installer clones this repository into `usr/plugins/tree_ring_memory`. Existing memory under `usr/memory/tree_ring_memory` is preserved across updates and uninstall. The community marketplace entry uses the same repository and manifest.

## Requirements

- Agent Zero with this directory mounted at `/a0/usr/plugins/tree_ring_memory/`.
- An executable `tree-ring` 0.12.x binary. The plugin requires at least 0.12.0 and fails closed on other minor versions. The published plugin bundles Linux binaries for Agent Zero's `x86_64` and `aarch64` Docker runtimes.
- Python 3.12+ in the Agent Zero framework runtime.

Binary discovery order:

1. `TREE_RING_MEMORY_CLI` or `cli.binary`.
2. `/a0/usr/plugins/tree_ring_memory/bin/linux-<architecture>/tree-ring`.
3. `/a0/usr/plugins/tree_ring_memory/bin/tree-ring` for an operator-supplied generic fallback.
4. `<memory-root>/bin/tree-ring`.
5. `tree-ring` on the framework runtime `PATH`.

Check readiness from the Agent Zero root:

```bash
python3 -m usr.plugins.tree_ring_memory.execute status
```

Both published Linux binaries are built from the exact upstream v0.12.0 tag in matching Rust Linux environments. Building the x86-64 target on Debian Bookworm also avoids the newer GLIBC requirement of the upstream release archive, while upstream v0.12.0 does not publish a Linux ARM64 archive at all. Operators on another platform can use Tree Ring's official installer or build from source, then configure `cli.binary` or place the executable at `usr/plugins/tree_ring_memory/bin/tree-ring`.

Binary installation is intentionally not hidden inside the plugin install hook. The plugin selects only the executable packaged for the running Docker architecture; any replacement download or build remains an explicit operator action.

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

Uninstall preserves both stores. Purge requires the explicit `purge --confirm` command.

## Legacy Migration

Migration never edits or deletes the old SQLite database. It reads `raw_json`, normalizes Python-v1 null/string and `chat`-scope differences, writes a mode-`0600` temporary JSONL file, validates that file with `tree-ring import --dry-run`, and imports through the Rust CLI only after confirmation. The temporary file is removed after the attempt.

Preview:

```bash
python3 -m usr.plugins.tree_ring_memory.execute migrate
```

Import after reviewing the preview:

```bash
python3 -m usr.plugins.tree_ring_memory.execute migrate --confirm
```

Migration is idempotent. A marker under `<memory-root>/migrations/` prevents accidental repeats, while the Rust importer also skips duplicate IDs by default. `--force` reruns validation/import without deleting or replacing existing canonical records.

## Agent Tools

- `remember`: concise memory through the upstream `remember` surface.
- `evidence`: evaluated outcomes with a required evidence reference.
- `recall`: Rust-ranked recall with optional Agent Zero ring/event post-filters.
- `forget`: explicit-ID delete or redact.
- `consolidate`: daily, weekly, monthly, yearly, or manual consolidation.
- `audit_memory`: non-mutating quality, privacy, and integrity audit.
- `maintain_memory`: dry-run maintenance or explicit expiry/redaction/FTS repair.
- `sync_dox`: DOX source adapter; dry-run by default.
- `sync_revolve`: Revolve evidence adapter; dry-run by default.
- `import_memory`: dry-run by default, with optional duplicate replacement.
- `export_memory`: canonical JSONL export.

The v0.12 CLI does not expose query-wide forget, selected-memory export, Markdown/SQLite export, expiry, or supersession as scriptable commands. The plugin returns an explicit unsupported-operation error for those former Python-v1 surfaces.

## Web UI

![Tree Ring Memory dashboard](screenshots/tree-ring-memory-dashboard.png)

The panel provides runtime readiness, search, ring/event filters, memory detail, ring-derived copies, delete/redact, consolidation, safe DOX/Revolve previews, audit, and canonical JSONL export. Its concentric Tree Ring visual illuminates each ring relative to the busiest ring, while the adjacent ledger shows exact record counts and share of the store; selecting a ring filters the live results. The settings view contains only values the bridge actually consumes: binary/version/timeout, storage paths, and recall limits.

When the CLI is missing or incompatible, the panel stays available and shows the concrete readiness error instead of initializing a second store.

## Maintenance

```bash
python3 -m usr.plugins.tree_ring_memory.execute status
python3 -m usr.plugins.tree_ring_memory.execute init
python3 -m usr.plugins.tree_ring_memory.execute audit
python3 -m usr.plugins.tree_ring_memory.execute maintain
python3 -m usr.plugins.tree_ring_memory.execute repair-fts
python3 -m usr.plugins.tree_ring_memory.execute export
python3 -m usr.plugins.tree_ring_memory.execute import-preview --path usr/memory/tree_ring_memory/imports/example.jsonl
python3 -m usr.plugins.tree_ring_memory.execute integrations --source-root .
python3 -m usr.plugins.tree_ring_memory.execute purge --confirm
```

`maintain` is report-only unless an apply flag is supplied. Sensitive recall and export remain opt-in. DOX `AGENTS.md`, Revolve evidence, current source, tests, and explicit user instructions remain authoritative over recalled memory.

## Verification

Focused tests use temporary roots and make no network calls. Set `TREE_RING_MEMORY_CLI` to include the real Rust round trip:

```bash
TREE_RING_MEMORY_CLI=/path/to/tree-ring \
PYTHONPATH="$PWD" \
PYTHONDONTWRITEBYTECODE=1 \
python3 -m pytest -q -p no:cacheprovider usr/plugins/tree_ring_memory/tests

node --check usr/plugins/tree_ring_memory/webui/memory-store.js
```

For upstream certification, put the freshly built `target/release/tree-ring` on `PATH` and set `TREE_RING_AGENT_ZERO_ROOT` to this Agent Zero checkout.

## Contribution Boundary

Keep implementation under `usr/plugins/tree_ring_memory/` and the companion guidance under `usr/skills/tree-ring-memory/`. Do not modify Agent Zero core code for this integration. If upstream changes its CLI or JSON schema, update the adapter and version gate together, then rerun the real CLI and legacy-copy proofs before changing the supported series.
