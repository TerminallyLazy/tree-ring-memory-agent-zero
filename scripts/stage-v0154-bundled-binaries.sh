#!/bin/sh
# Stage the two native outputs of the pinned v0.15.4 workflow into this plugin.
#
# This script deliberately accepts only the two GitHub Actions artifacts made by
# .github/workflows/build-bundled-binaries.yml for the released Tree Ring v0.15.4 tag.
# It does not download, build, tag, or publish anything.
set -eu

usage() {
  printf '%s\n' "usage: $0 <linux-x86_64-artifact-dir> <linux-aarch64-artifact-dir>" >&2
  exit 64
}

[ "$#" -eq 2 ] || usage

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PLUGIN_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
X86_ARTIFACT=$1
ARM_ARTIFACT=$2
EXPECTED_TAG=v0.15.4
EXPECTED_VERSION='tree-ring 0.15.4'
EXPECTED_REPOSITORY=https://github.com/TerminallyLazy/Tree-Ring-Memory
EXPECTED_IMAGE='rust:1.95-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1'

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    printf '%s\n' "error: sha256sum or shasum is required" >&2
    exit 69
  fi
}

provenance_value() {
  key=$1
  file=$2
  value=$(sed -n "s/^${key}=//p" "$file")
  [ "$(printf '%s\n' "$value" | sed '/^$/d' | wc -l | tr -d ' ')" -eq 1 ] || {
    printf '%s\n' "error: expected exactly one $key entry in $file" >&2
    exit 65
  }
  printf '%s\n' "$value"
}

require_provenance() {
  key=$1
  expected=$2
  file=$3
  actual=$(provenance_value "$key" "$file")
  [ "$actual" = "$expected" ] || {
    printf '%s\n' "error: expected $key=$expected in $file, got $actual" >&2
    exit 65
  }
}

verify_artifact() {
  artifact=$1
  expected_machine=$2
  expected_runner=$3

  [ -d "$artifact" ] || {
    printf '%s\n' "error: artifact directory does not exist: $artifact" >&2
    exit 66
  }
  for name in tree-ring SHA256SUM PROVENANCE.txt; do
    [ -f "$artifact/$name" ] && [ ! -L "$artifact/$name" ] || {
      printf '%s\n' "error: artifact is missing a regular $name file: $artifact" >&2
      exit 65
    }
  done
  [ -x "$artifact/tree-ring" ] || {
    printf '%s\n' "error: artifact tree-ring is not executable: $artifact" >&2
    exit 65
  }

  checksum_line=$(cat "$artifact/SHA256SUM")
  expected_checksum=$(printf '%s\n' "$checksum_line" | sed -n 's/^\([0-9a-f][0-9a-f]*\)  tree-ring$/\1/p')
  [ "$(printf '%s\n' "$checksum_line" | wc -l | tr -d ' ')" -eq 1 ] && \
    [ "${#expected_checksum}" -eq 64 ] || {
      printf '%s\n' "error: SHA256SUM must contain one sha256sum entry for tree-ring: $artifact" >&2
      exit 65
    }
  actual_checksum=$(sha256_file "$artifact/tree-ring")
  [ "$actual_checksum" = "$expected_checksum" ] || {
    printf '%s\n' "error: tree-ring checksum does not match SHA256SUM: $artifact" >&2
    exit 65
  }

  provenance="$artifact/PROVENANCE.txt"
  require_provenance source_repository "$EXPECTED_REPOSITORY" "$provenance"
  require_provenance source_tag "$EXPECTED_TAG" "$provenance"
  source_commit=$(provenance_value source_commit "$provenance")
  printf '%s\n' "$source_commit" | grep -Eq '^[0-9a-f]{40}$' || {
    printf '%s\n' "error: source_commit must be a resolved 40-character commit: $artifact" >&2
    exit 65
  }
  require_provenance build_image "$EXPECTED_IMAGE" "$provenance"
  require_provenance runner "$expected_runner" "$provenance"
  require_provenance machine "$expected_machine" "$provenance"
  require_provenance binary_version "$EXPECTED_VERSION" "$provenance"

  printf '%s\n' "$source_commit"
}

x86_commit=$(verify_artifact "$X86_ARTIFACT" x86_64 ubuntu-24.04)
arm_commit=$(verify_artifact "$ARM_ARTIFACT" aarch64 ubuntu-24.04-arm)
[ "$x86_commit" = "$arm_commit" ] || {
  printf '%s\n' "error: artifacts were built from different Tree Ring commits" >&2
  exit 65
}

stage_dir=$(mktemp -d "${TMPDIR:-/tmp}/tree-ring-v0154-stage.XXXXXX")
cleanup() {
  rm -rf "$stage_dir"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$stage_dir/linux-x86_64" "$stage_dir/linux-aarch64"
for target in linux-x86_64 linux-aarch64; do
  if [ "$target" = linux-x86_64 ]; then
    source_dir=$X86_ARTIFACT
  else
    source_dir=$ARM_ARTIFACT
  fi
  install -m 0755 "$source_dir/tree-ring" "$stage_dir/$target/tree-ring"
  install -m 0644 "$source_dir/PROVENANCE.txt" "$stage_dir/$target/PROVENANCE.txt"
done
{
  sha256_file "$stage_dir/linux-aarch64/tree-ring" | awk '{print $1 "  bin/linux-aarch64/tree-ring"}'
  sha256_file "$stage_dir/linux-x86_64/tree-ring" | awk '{print $1 "  bin/linux-x86_64/tree-ring"}'
} > "$stage_dir/SHA256SUMS"

for target in linux-x86_64 linux-aarch64; do
  install -m 0755 "$stage_dir/$target/tree-ring" "$PLUGIN_ROOT/bin/$target/tree-ring"
  install -m 0644 "$stage_dir/$target/PROVENANCE.txt" "$PLUGIN_ROOT/bin/$target/PROVENANCE.txt"
done
install -m 0644 "$stage_dir/SHA256SUMS" "$PLUGIN_ROOT/bin/SHA256SUMS"

printf '%s\n' "staged Tree Ring $EXPECTED_VERSION from $x86_commit"
