# Bundled Tree Ring CLI

These executables are built from Tree Ring Memory tag `v0.13.0`, commit
`167bc655e001112ff5593d7af0984b3e8689ea1a`, using the locked dependency graph
and the pinned
`rust:1.95-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1`
build image for each target architecture.

- `linux-aarch64/tree-ring` supports ARM64 Agent Zero Docker runtimes.
- `linux-x86_64/tree-ring` supports x86-64 Agent Zero Docker runtimes.

Both were built and tested on native GitHub runners in
[workflow run 30046094259](https://github.com/TerminallyLazy/tree-ring-memory-agent-zero/actions/runs/30046094259).
They are dynamically linked against Debian Bookworm's GLIBC 2.36 baseline and
require at most GLIBC 2.34, so they run in the current Agent Zero image. The
plugin selects only the binary matching the running Linux architecture and
never downloads an executable during installation.

Each architecture directory includes the immutable source, toolchain, runner,
runtime, and binary-version evidence captured in `PROVENANCE.txt`.

From the plugin root, verify the packaged files with:

```bash
sha256sum -c bin/SHA256SUMS
```
