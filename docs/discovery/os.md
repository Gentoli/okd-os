# OpenShift OS image build and RPM installation

This documents [`openshift/os` at commit
`3d00d375d491de94fd9dcd0b5440a0efbec3d9db`](https://github.com/openshift/os/tree/3d00d375d491de94fd9dcd0b5440a0efbec3d9db),
before the `c9s` references were removed. The key distinction is that this
repository builds the final OpenShift/OKD node image on top of a separate
RHCOS/SCOS base; it does not build that base or compile its RPMs.

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
- `test-rpm-install` downloads the artifacts, runs in a CentOS Stream 9
  container, and installs the local files with `dnf install -y "${rpms[@]}"`.
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
  documents using COSA with `cosa init --variant scos`, `cosa fetch`, and
  `cosa build`.
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

In particular, this repository's
[`build-push.yml`](../../.github/workflows/build-push.yml#L36-L41) extracts
`stream-coreos` from an OKD release payload. The upstream README identifies
that `stream-coreos` image as the final node image built by `openshift/os`,
not the separate SCOS base. Using it as `c9s-coreos` would therefore use the
wrong image layer.

**Version caveat:** the pinned upstream build guide's example refers to SCOS
4.21 and an RHEL 9.6 base, while the same commit's package manifest targets
OpenShift 4.22 and its CI repository setup includes RHEL 9.8. Treat those
example version strings as stale for this snapshot.
