# Bundled Tree Ring CLI

Plugin `3.4.1` requires Tree Ring `0.15.7` through `0.15.x` because automatic
capture depends on `tree-ring capture`. These executables are built from
immutable Tree Ring Memory tag `v0.15.7`, commit
`8319b40d848ac9d2da0df513bb54350b47e8f0bd`, using the locked dependency graph
and pinned
`rust:1.95-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1`
build image on each native target architecture.

- `linux-aarch64/tree-ring` supports ARM64 Agent Zero Docker runtimes.
- `linux-x86_64/tree-ring` supports x86-64 Agent Zero Docker runtimes.

Both were built and tested on native GitHub runners by the manual **Prepare Tree
Ring 0.15.7 bundled binaries** [workflow run
34273197248](https://github.com/TerminallyLazy/tree-ring-memory-agent-zero/actions/runs/34273197248).
They are dynamically linked against
the Debian Bookworm GLIBC 2.36 baseline, and the workflow rejects a binary that
requires a newer GLIBC. The plugin selects only the binary matching the running
Linux architecture and never downloads executable code during installation.

Each architecture directory includes the immutable source, toolchain, runner,
runtime, and binary-version evidence captured in `PROVENANCE.txt`.

From the plugin root, verify the packaged files with:

```bash
sha256sum -c bin/SHA256SUMS
# On macOS: shasum -a 256 -c bin/SHA256SUMS
```

## Rebuilding the verified bundle

Manually run the pinned **Prepare Tree Ring 0.15.7 bundled binaries** GitHub
Actions workflow. It checks out the exact
tag, resolves it to a 40-character commit, runs the activation and multi-agent
CLI acceptance tests, verifies `tree-ring capture --help`, records that command
check in provenance, and emits one native artifact for each Agent Zero runtime:

- `tree-ring-v0.15.7-linux-x86_64`
- `tree-ring-v0.15.7-linux-aarch64`

Download both artifacts from the same successful workflow run, then run this
from the plugin checkout (substituting their downloaded directories):

```bash
scripts/stage-v0157-bundled-binaries.sh \
  /absolute/path/to/tree-ring-v0.15.7-linux-x86_64 \
  /absolute/path/to/tree-ring-v0.15.7-linux-aarch64
sha256sum -c bin/SHA256SUMS
# On macOS: shasum -a 256 -c bin/SHA256SUMS
```

The staging command accepts only regular, checksum-matching files with
`v0.15.7` provenance, the pinned Bookworm image, the expected native runner and
machine, `tree-ring 0.15.7`, and the same resolved core commit for both
architectures. It also requires `capture_command=verified`, which the pinned
native build workflow writes only after the command help check succeeds. The
stager neither downloads nor builds code. Review the complete `bin/` diff and
rerun the real-CLI package suite before release.
