# Bundled Tree Ring CLI

Plugin `3.4.2` requires Tree Ring `0.15.12` through `0.15.x` because receipt-backed
activation requires the exact `3.4.2` capability contract. This runtime also
includes atomic DOX source-provenance guards and `tree-ring capture`. These
executables are built from
immutable Tree Ring Memory tag `v0.15.12`, commit
`e9433e281c9743988a194f5af36a8258f2b9cc68`, using the locked dependency graph
and pinned
`rust:1.95-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1`
build image on each native target architecture.

- `linux-aarch64/tree-ring` supports ARM64 Agent Zero Docker runtimes.
- `linux-x86_64/tree-ring` supports x86-64 Agent Zero Docker runtimes.

Both were built and tested on native GitHub runners by the manual **Prepare Tree
Ring 0.15.12 bundled binaries** [workflow run
35026514548](https://github.com/TerminallyLazy/tree-ring-memory-agent-zero/actions/runs/35026514548).
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

Manually run the pinned **Prepare Tree Ring 0.15.12 bundled binaries** GitHub
Actions workflow. It checks out the exact
tag, resolves it to a 40-character commit, runs the activation and multi-agent
CLI acceptance tests plus the SQLite DOX and shared-adapter regressions, verifies
`tree-ring capture --help`, and runs `scripts/verify-activation-pair.py` against
the built executable with this plugin checkout's actual manifest and capability
descriptor. It records those checks in provenance and emits one native artifact
for each Agent Zero runtime:

- `tree-ring-v0.15.12-linux-x86_64`
- `tree-ring-v0.15.12-linux-aarch64`

Download both artifacts from the same successful workflow run, then run this
from the plugin checkout (substituting their downloaded directories):

```bash
scripts/stage-v01512-bundled-binaries.sh \
  /absolute/path/to/tree-ring-v0.15.12-linux-x86_64 \
  /absolute/path/to/tree-ring-v0.15.12-linux-aarch64
sha256sum -c bin/SHA256SUMS
# On macOS: shasum -a 256 -c bin/SHA256SUMS
```

The staging command accepts only regular, checksum-matching files with
`v0.15.12` provenance, the pinned Bookworm image, the expected native runner and
machine, `tree-ring 0.15.12`, and the same resolved core commit for both
architectures. It also requires `capture_command=verified`,
`dox_source_guard=verified`, and
`agent_zero_activation=verified`, which the pinned native build workflow writes
only after the command, guarded DOX, and actual plugin activation checks succeed.
The stager neither downloads nor builds code. Review the complete `bin/` diff and
rerun the real-CLI package suite before release.

Before tagging either repository's release, run the same pairing smoke against
the candidate core binary and the current plugin files:

```bash
python3 scripts/verify-activation-pair.py /absolute/path/to/candidate/tree-ring
```

The core accepts exact capability tuples. A new plugin version/minimum requires
its corresponding core contract and a passing receipt-backed pairing test; do
not reuse an older descriptor or broaden the allowlist to make a release pass.
The native workflow repeats this proof before uploading either artifact, and
release validation reruns the real Python bridge tests against both bundles.
