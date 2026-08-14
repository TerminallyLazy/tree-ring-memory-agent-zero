# Bundled Tree Ring CLI

## Pending 3.1.0 release gate

Plugin source `3.1.0` requires Tree Ring `0.14.x`, but the files below are
unchanged `v0.13.0` release artifacts. They remain only as historical checksum
and provenance evidence. Do **not** install, publish, rename, or claim them as
compatible `0.14` binaries. Replace them only after the immutable core
`v0.14.0` tag produces matching native Linux artifacts, checksums, and
provenance.

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
# On macOS: shasum -a 256 -c bin/SHA256SUMS
```

## Replacing the historical artifacts for 3.1.0

After—not before—the core `v0.14.0` tag exists, manually run the pinned
`Prepare Tree Ring 0.14 bundled binaries` GitHub Actions workflow. It checks
out that exact tag, resolves the tag to a 40-character commit at runtime, runs
the activation and multi-agent CLI acceptance tests, and emits one native
artifact for each Agent Zero runtime:

- `tree-ring-v0.14.0-linux-x86_64`
- `tree-ring-v0.14.0-linux-aarch64`

Download both artifacts from the same successful workflow run, then run this
from the plugin checkout (substituting their downloaded directories):

```bash
scripts/stage-v014-bundled-binaries.sh \
  /absolute/path/to/tree-ring-v0.14.0-linux-x86_64 \
  /absolute/path/to/tree-ring-v0.14.0-linux-aarch64
sha256sum -c bin/SHA256SUMS
# On macOS: shasum -a 256 -c bin/SHA256SUMS
```

The staging command accepts only regular, checksum-matching files with
`v0.14.0` provenance, the pinned Bookworm image, the expected native runner
and machine, `tree-ring 0.14.0`, and the same resolved core commit for both
architectures. It neither downloads nor builds code. Review the resulting
`bin/` diff and update this document and the release boundary in the root
README from pending to released only after real-core certification passes.
