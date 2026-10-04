# OpenShift OS image build and RPM installation

This documents [`openshift/os` at commit
`3d00d375d491de94fd9dcd0b5440a0efbec3d9db`](https://github.com/openshift/os/tree/3d00d375d491de94fd9dcd0b5440a0efbec3d9db),
before the `c9s` references were removed. The key distinction is that this
repository builds the final OpenShift/OKD node image on top of a separate
RHCOS/SCOS base; it does not build that base or compile its RPMs.

The image workflow scans stable OKD releases 4.20, 4.21, and 4.22 and builds
both `c9s` and `c10s` outputs. When a release payload lacks a matching
`stream-coreos` image, it checks out the corresponding `openshift/os` release
branch and composes from the latest SCOS base. The 4.20 source details below
remain a historical example: that source uses `c9s-coreos`; its manifest selects
CentOS 9 and the
`rhel-9.6-server-ose-4.20-okd` repo alias. The corresponding
[`openshift/release` 4.20 config](https://github.com/openshift/release/blob/main/ci-operator/config/openshift/os/openshift-os-release-4.20.yaml)
maps the RHEL 9.6 base input to `c9s-coreos`.
The historical workflow pin and repo details are recorded in
[`okd-os.md`](../../okd-os.md).

## Build and package flow

The upstream [README](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/README.md)
identifies `rhel-coreos` and `stream-coreos` as the node images included in a
release payload. The separate
[`coreos/rhel-coreos-config`](https://github.com/coreos/rhel-coreos-config/tree/45a6e864f6829e852fd17174cd9da1e13b4e70fa)
project builds the RHCOS/SCOS base with coreos-assembler (COSA); its README
describes that image as containing RHEL or CentOS Stream content, without
OpenShift components.

At the pinned `openshift/os` commit:

1. The [`Containerfile`](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/Containerfile)
   starts from the private `quay.io/openshift-release-dev/ocp-v4.0-art-dev:c9s-coreos`
   image. It mounts the source tree and a yum-repository secret, then runs
   `build-node-image.sh`.
2. [`build-node-image.sh`](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/build-node-image.sh)
   makes the configured RPM repositories available and runs
   `rpm-ostree experimental compose treefile-apply` with
   [`packages-openshift.yaml`](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/packages-openshift.yaml).
   The manifest selects repositories by OS version and names packages such
   as `cri-o`, `cri-tools`, `conmon-rs`, `openshift-clients`,
   `openshift-kubelet`, and the credential providers. This composes already
   published RPMs into the OSTree-based node image; it is not an RPM source
   build.
3. The `Containerfile` generates metadata in a build stage, then copies it
   into the final image. The extensions image is built separately.

The upstream snapshot has no GitHub Actions workflow for this build, and its
[`.prow.sh`](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/.prow.sh)
is a no-op. Image CI is configured in
[`openshift/release`](https://github.com/openshift/release/blob/06c6fdbe105cccc2e7a06d4dd23cae71b8caaeda/ci-operator/config/openshift/os/openshift-os-release-4.22.yaml):
Prow runs `ci-operator --target=[images]`, supplies the base image input and
repository secrets, and builds the configured image. Its optional E2E job
tests the resulting release image. The upstream
[build guide](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/docs/building.md)
also notes that composing the full node image requires internal yum-repository
files and either an OpenShift pull secret or a locally built base.

## Installing this repository's RPM artifacts in GitHub Actions

This repository already demonstrates the straightforward RPM-install test in
[`rpm-build.yml`](../../.github/workflows/rpm-build.yml#L283-L316):

- The build jobs upload RPMs as workflow artifacts.
- `test-rpm-install` downloads the version/stream-matched artifacts, runs in a
  matching CentOS Stream 9 or 10 container, and installs them with
  `dnf install -y "${rpms[@]}"`.
  It enables the repositories needed for dependency resolution first.
- The following step checks that packaged executables exist and records their
  version output.

This verifies the built RPMs install without needing to publish them to a
registry or use the private OpenShift base image. It is a package-install test,
not a reproduction of the `rpm-ostree` node-image composition. To include
these RPMs in a composed node image, make them available from a repository
with metadata and have the compose use that repository and package set.

## Base-image availability and alternatives

The `c9s-coreos` name in the `Containerfile` is the base input used by the
upstream build, not an image that can be pulled anonymously from the private
`openshift-release-dev` repository. Docker pulls of that image and the
plausible `quay.io/coreos/stream-coreos-base:9` tag returned unauthorized in
the checks for this discovery. I did not find an anonymously pullable,
version-matched replacement for the exact base input.

For SCOS, the public source-based alternative is to build the base rather than
substitute another release image:

- [`coreos/rhel-coreos-config`'s SCOS development guide](https://github.com/coreos/rhel-coreos-config/blob/45a6e864f6829e852fd17174cd9da1e13b4e70fa/docs/development-scos.md)
  documents building the SCOS base with COSA. At this pinned config commit the
  actual variant is `c9s` (not `scos`); `cosa init --variant scos` fails because
  there are no `manifest-scos.yaml` or `image-scos.yaml` files. `cosa fetch`
  also reports that it is skipped because build-with-buildah is now the default.
- Its [`c9s` build arguments](https://github.com/coreos/rhel-coreos-config/blob/45a6e864f6829e852fd17174cd9da1e13b4e70fa/build-args-c9s.conf)
  use the public `quay.io/centos-bootc/centos-bootc:stream9` image as a build
  input. That image is a builder input, not the resulting CoreOS base; the
  COSA build produces the SCOS base artifact.
- The upstream build guide documents passing a locally built COSA OCI archive
  with `--from oci-archive:...`.

This route provides public source and build inputs, but it is not a direct
pull of the private image or a guarantee that the full OpenShift node compose
will work on an unauthenticated GitHub runner. The RPM repositories and
credentials required by the node-image composition still need to be supplied.
The public `quay.io/okd/centos-stream-coreos-9:4.18-x86_64` tag is also not a
base-image substitute: it is an older, bootable final node image. A Docker
pull and package query showed OpenShift packages including `cri-o`,
`openshift-kubelet`, and `openshift-clients` already in it.

The
[`build-okd-stream-coreos.yml`](../../.github/workflows/build-okd-stream-coreos.yml)
workflow may use `stream-coreos` from an OKD release payload as the starting
image for its kernel overlay. That payload image is the final node image built
by `openshift/os`, not the separate SCOS base. When no matching payload image is
available, the workflow builds the matching RPMs and composes the machine image
on top of `scos-base` in the same run.

**Version caveat:** the pinned upstream build guide's example refers to SCOS
4.21 and an RHEL 9.6 base, while the same commit's package manifest targets
OpenShift 4.22 and its CI repository setup includes RHEL 9.8. Treat those
example version strings as stale for this snapshot.

## Attempted COSA build

I ran the pinned `coreos/rhel-coreos-config` build in a temporary directory
using the public `quay.io/coreos-assembler/coreos-assembler:latest` builder.
Because a GitHub source archive does not include `.git` metadata, the local
test initialized synthetic Git metadata; the published artifact therefore
does not claim to be a clean upstream build.

- `cosa init --variant scos` failed as described above. Retrying with the
  config's actual `c9s` variant initialized successfully; `cosa fetch` was a
  no-op.
- The unmodified `cosa build` failed at RPM resolution with
  `Packages not found: fwupd-plugin-flashrom`. A separate DNF query against
  the public Stream 9 repositories did list that RPM, so the exact reason it
  was unavailable to the compose was not determined.
- Removing the `fwupd-plugin-flashrom` conditional package block in the
  temporary source let the diagnostic build complete. COSA built and imported
  a bootable x86_64 SCOS OCI image, tagged
  `9.0.20260926-dev0`, with OCI digest
  `sha256:fbd97dca3b40485db686561c6d289dd2bc26466b558cb0cd6844ad34e00a287f`.
  The OCI archive was about 1.35 GB. This is a test result, not a pristine
  reproducible build.
- The corresponding compatibility patch is
  [`0001-drop-unresolvable-fwupd-plugin.patch`](../../os/base/c9s/patches/0001-drop-unresolvable-fwupd-plugin.patch).
  It is retained as a one-time bootstrap input until the first CI mirror
  publication. [`build-scos-base.yml`](../../.github/workflows/build-scos-base.yml)
  calls the shared [`sync-repo-mirror.yml`](../../.github/workflows/sync-repo-mirror.yml)
  workflow before each base build. That workflow checks the upstream default
  branch against `Gentoli/okd-os:coreos/c9s`, applies the seed patch only when
  creating the branch, and replays its compatibility commit on later upstream
  updates. The builder checks out `coreos/c9s`; it no longer applies local
  patch files. Workflow dispatch no longer accepts an upstream `config_ref`.
  After the mirror branch and first base build are verified, the seed patch can
  be deleted. Pushes run on `main` when the workflow or base files change. The
  workflow publishes `scos-base:c9s` as the SCOS OCI base and
  `scos-base:c9s-vm` as the QEMU VM image containing the disk. The SCOS OCI
  base includes source revision labels.
- `docker/login-action` provides the GHCR credentials used when publishing.
  The action's post-job cleanup logs out at the end of the job.
- The COSA job container requires a runner with `/dev/kvm`; the workflow fails
  early if that device is unavailable.
