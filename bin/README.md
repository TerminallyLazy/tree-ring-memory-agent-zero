# Bundled Tree Ring CLI

These executables are built from Tree Ring Memory tag `v0.12.0`, commit
`67192a7455cd38df5106e113d2ab537164d13788`, using the locked dependency graph
and the official `rust:1.95-bookworm` build image for each target architecture.

- `linux-aarch64/tree-ring` supports ARM64 Agent Zero Docker runtimes.
- `linux-x86_64/tree-ring` supports x86-64 Agent Zero Docker runtimes.

Both are dynamically linked against the Debian Bookworm baseline (GLIBC 2.36)
so they also run in the current Agent Zero image. The plugin selects only the
binary matching the running Linux architecture and never downloads an
executable during installation.

From the plugin root, verify the packaged files with:

```bash
sha256sum -c bin/SHA256SUMS
```
