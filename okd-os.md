# Building OKD images from stable release payloads and SCOS bases

## Release matrix

The push/scheduled/manual `scan-okd-releases.yml` workflow currently scans the
4.22-c9s, 4.22-c10s, and 4.20-c9s targets. It calls the reusable
`build-okd-stream-coreos.yml` workflow for each target. A matching
`stream-coreos` image in the release payload is reused and receives only the
kernel/GCC overlays. If no matching c9s image exists, the same workflow run
builds the matching RPMs, composes the machine image from `scos-base:c9s`, then
builds the overlays. A c10s target without a matching release image is skipped.

## Historical 4.20 compose details

The earlier node-image workflow targeted `openshift/os` commit
[`847b7d8c3b60f60e86f1de0b7efebb746c75d1bc`](https://github.com/openshift/os/tree/847b7d8c3b60f60e86f1de0b7efebb746c75d1bc)
from `release-4.20`. This was checked at that exact commit: its
[`Containerfile`](https://github.com/openshift/os/blob/847b7d8c3b60f60e86f1de0b7efebb746c75d1bc/Containerfile)
still starts from `c9s-coreos`; its
[`packages-openshift.yaml`](https://github.com/openshift/os/blob/847b7d8c3b60f60e86f1de0b7efebb746c75d1bc/packages-openshift.yaml)
targets `4.20`, uses the CentOS 9 package set, and includes
`rhel-9.6-server-ose-4.20-okd`. The 4.20 build script takes the corresponding
`rhel-9.6-server-ose-4.20` stanza from the repository file and renames it to
that manifest alias. The manifest requests the AWS, Azure, and GCP credential
providers, but not the CRI-O credential provider. The RPM and node-image
workflows follow those requirements. The matching
[`openshift/release` 4.20 config](https://github.com/openshift/release/blob/main/ci-operator/config/openshift/os/openshift-os-release-4.20.yaml)
maps its RHEL 9.6 base input to the same `c9s-coreos` alias.

There is no public `4.20` tag in `quay.io/okd/centos-stream-coreos-9`. The Kola
workflow instead resolves the upstream `stream-coreos` image from a pinned
`quay.io/okd/scos-release` payload, matching the repository's release-image
build workflow. The `4.22` compose investigation and run results below are
retained as historical findings, not current workflow configuration.

This research follows [`openshift/os` at
`3d00d375d491de94fd9dcd0b5440a0efbec3d9db`](https://github.com/openshift/os/tree/3d00d375d491de94fd9dcd0b5440a0efbec3d9db)
and uses the public base image
`ghcr.io/gentoli/scos-base:c9s`.

## What this build produces

`openshift/os` builds the final SCOS/OKD node image (`stream-coreos`) by adding
OpenShift packages to an existing CoreOS base. It does not build the base image
or compile the RPMs. The base comes from `coreos/rhel-coreos-config`; the
`openshift/os` build composes already-published RPMs into the final OSTree-based
container image. The optional extensions image is a separate build.

This repository's `scos-base:c9s` image is a suitable public base input:
an anonymous `skopeo inspect` returned digest
`sha256:27818dd2e0f2097df2e6a9c5518ae737a939d416e3f3a352f26fc05a2c1331d1`,
architecture `amd64`, `com.coreos.osname=scos`, and `com.coreos.stream=c9s`.
Running it confirmed `ID=centos`, `VERSION_ID=9`, and
`VERSION="9.0.20260926-dev0"`. Thus the compose script selects the `centos-9`
package set. The public image removes the need for an OpenShift pull secret just
to obtain the base; it does not provide the OpenShift RPM repositories.

This confirms compatibility at the OS-family and image-role level, not
byte-for-byte equivalence with the private upstream base. The `c9s` tag is
mutable. The base workflow builds that variant from `coreos/rhel-coreos-config`
and labels it with the config commit and workflow commit. It publishes the
OCI base as `<stream>` and the QEMU disk container as `<stream>-vm`.

## How the pinned build composes the image

The upstream [`Containerfile`](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/Containerfile)
starts from the private `quay.io/openshift-release-dev/ocp-v4.0-art-dev:c9s-coreos`
image. Its build step mounts the source tree at `/run/src`, mounts a required
`yumrepos` Buildah secret at `/etc/yum.repos.d/secret.repo`, and runs
[`build-node-image.sh`](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/build-node-image.sh).
The upstream [build guide](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/docs/building.md)
documents overriding the base with `podman build --from ...`.

For a local build, the script combines the repository's `.repo` files with the
secret repository file. On CentOS it takes the
`rhel-9.8-server-ose-4.22` repository definition from those files, renames it
`rhel-9.8-server-ose-4.22-okd`, and limits it to the allowed OpenShift package
families. It then runs:

```text
rpm-ostree experimental compose treefile-apply \
  --var osversion=centos-9 /run/src/packages-openshift.yaml
```

The [`packages-openshift.yaml`](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/packages-openshift.yaml)
manifest selects CentOS Stream 9 BaseOS, AppStream, NFV, and Cloud SIG
repositories plus `rhel-9.8-server-ose-4.22-okd`. It installs packages
including `cri-o`, `cri-tools`, `conmon-rs`, `openshift-clients`,
`openshift-kubelet`, `openvswitch3.5`, and the cloud credential providers.
After composition, the script removes injected repo files and commits the
OSTree container. A metadata stage generates `/usr/share/openshift`, which is
copied into the final image.

The local build guide's sample output tag says `4.21`, while this pinned
manifest and release configuration target OpenShift `4.22`; use a `4.22` tag
for this snapshot. Those guide examples are stale for this pinned source.
There is additional repo-version skew: the pinned
[`c9s.repo`](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/c9s.repo#L67-L76)
points `c9s-sig-cloud-okd` at the OKD 4.20 directory and comments that it needs
updating to 4.21, even though the package manifest selects it in a 4.22 build.
Do not assume the public repo definitions alone supply the pinned package set.

## Required repository access

The SCOS base alone is not enough to complete the node-image build. The
upstream guide says the build needs the canonical yum repository files used by
RHCOS, obtained from an internal Red Hat repository, and access to those
repositories. For this pinned CentOS manifest, the compose specifically needs
the `rhel-9.8-server-ose-4.22` stanza so the build script can expose the
expected `rhel-9.8-server-ose-4.22-okd` repo. The internal repo CA may also need
to be mounted into the build container. The upstream guide's sample command is:

```sh
podman build . \
  --secret id=yumrepos,src=/path/to/all.repo \
  -v /etc/pki/ca-trust:/etc/pki/ca-trust:ro \
  --security-opt label=disable \
  -t localhost/stream-coreos:4.22
```

With this repository's public base, override the upstream private `FROM`:

```sh
podman build . \
  --from ghcr.io/gentoli/scos-base:c9s \
  --secret id=yumrepos,src=/path/to/all.repo \
  -v /etc/pki/ca-trust:/etc/pki/ca-trust:ro \
  --security-opt label=disable \
  -t localhost/stream-coreos:4.22-c9s
```

Run this from a checkout of the pinned `openshift/os` source. The `all.repo`
file must contain the needed repository definitions and the environment must
be authorized to fetch their packages. The CA-trust bind mount shown above is
needed when the internal repo requires the Red Hat CA; adapt or omit it only
when the build environment already trusts the repository endpoint. The
Containerfile defaults `OPENSHIFT_CI=0`, appropriate for local composition;
the pinned release CI sets it to `1` to retrieve an in-cluster mirror
configuration and also supplies its base image input and secrets.

## Build attempt in this session

The base image was publicly inspectable and Podman successfully pulled it. I
downloaded the pinned upstream source archive and ran its `Containerfile` with
`--from ghcr.io/gentoli/scos-base:c9s`. The first attempt stopped before
the build because this runner has no `/etc/pki/ca-trust` directory. Retrying
without that host bind mount reached `rpm-ostree` composition, but I supplied
an empty `yumrepos` secret because the internal repository configuration was
not available. The compose failed with:

```text
Warning: failed loading '/etc/yum.repos.d/okd.repo', skipping.
Error: Unknown repo: 'rhel-9.8-server-ose-4.22-okd'
```

This confirms that the public base is usable as the `FROM` image, but the final
node image was not produced here. A complete build still needs the repository
definitions, network access, and any credentials/CA certificates those
repositories require. No conclusion about a fully provisioned internal build
is implied by this failed attempt.

## Using RPM Actions artifacts as a local repo

The successful [RPM workflow run 36280633883](https://github.com/Gentoli/okd-os/actions/runs/36280633883)
uploaded six RPM ZIP artifacts: the CentOS SIG builds for `cri-o`,
`cri-tools`, and `conmon-rs`, and the `oc`, `kubernetes`, and
`crio-credential-provider` EL9 builds. Unpacking them produced 15 RPM files
(including debuginfo/debugsource RPMs). The artifacts are GitHub Actions
downloads, not DNF repositories: download and unpack them, then generate
`repodata` with `createrepo_c`.

A web host is not required for a one-off/local compose. I verified a local
repository by binding its directory into the build container and using a repo
file with `baseurl=file:///var/tmp/okd-rpm-repo`:

```sh
createrepo_c /path/to/rpms
cat > all.repo <<'EOF'
[rhel-9.8-server-ose-4.22]
name=Local OpenShift RPM artifacts
baseurl=file:///var/tmp/okd-rpm-repo
enabled=1
gpgcheck=0
EOF
podman build . \
  --from ghcr.io/gentoli/scos-base:c9s \
  --secret id=yumrepos,src=all.repo \
  --volume /path/to/rpms:/var/tmp/okd-rpm-repo:ro \
  --security-opt label=disable \
  -t localhost/stream-coreos:4.22
```

In this setup `rpm-ostree`/DNF successfully loaded the local repo metadata
alongside the CentOS repos. The retry got past the previous unknown-repo
failure, but composition still failed because four package names requested by
the pinned manifest are absent from the artifacts:

```text
No match for argument: ose-aws-ecr-image-credential-provider
No match for argument: ose-azure-acr-image-credential-provider
No match for argument: ose-crio-credential-provider
No match for argument: ose-gcp-gcr-image-credential-provider
```

The run contains `crio-credential-provider`, but its RPM metadata does not
provide the requested `ose-crio-credential-provider` name. It has none of the
other three `ose-*` provider RPMs either. Thus, the artifact set proves the
local-repo method works, but is incomplete for this pinned compose; hosting
these same artifacts would not fix the missing packages. The complete matching
RPM set must first be produced or obtained. For a diagnostic retry that omits
all four provider entries, the compose completes; see the source trace and
resulting image details in [`rpms.md`](docs/discovery/rpms.md). That output is
not an unmodified complete node image.

For recurring builds, keep artifact download, repo creation, and compose in the
same workflow run (or explicitly download those artifacts into the build job).
Actions artifacts expire (this run's bundles were set to expire after 90 days)
and are not stable repo URLs. A persistent HTTPS RPM host is useful when builds
must consume the same immutable package set independently of a particular
workflow run; publish the RPMs and `repodata` together, retain old versions, and
apply access control/signing appropriate to the packages. Do not point DNF at
the temporary artifact-download URL or at the ZIP itself.

## Current node-image workflow

The push/scheduled/manual
[`scan-okd-releases.yml`](.github/workflows/scan-okd-releases.yml) workflow
scans stable releases at
[okd-project/okd/releases](https://github.com/okd-project/okd/releases), ignoring
pre-releases, then builds the 4.22-c9s, 4.22-c10s, and 4.20-c9s targets. If a
matching `stream-coreos` image is present in a release payload, the reusable
[`build-okd-stream-coreos.yml`](.github/workflows/build-okd-stream-coreos.yml)
workflow uses it as the input and only applies the kernel/GCC overlay. It
prepares the source-image decision and fallback compose in separate jobs, so a
matching upstream image skips composition. If a c9s image is missing, it builds
the matching RPMs in the same workflow run and composes from the latest
`scos-base:c9s`; a c10s variant without an upstream image is skipped because no
c10s base is built. The other release/base matrix entries remain commented out
while testing.

For custom-composed images other than 4.22/EL9, the stream overlay preserves
the kernel already present in the composed image instead of running
`rpm-ostree override replace` against the same base package versions. The
driver-toolkit overlay uses that image's installed `kernel-core` version so its
kernel development packages stay in sync. The 4.22/EL9 overlay behavior is
unchanged.

The workflow publishes `stream-coreos:<version>-<stream>` and
`driver-toolkit:<version>-<stream>`. Each image records its release payload,
source image version/digest/revision, and workflow revision in OCI labels. The
RPM workflow accepts one version/EL target and optional SIG-build and
install-test flags. The image workflow owns the `strategy.matrix` and passes
each target to the reusable RPM workflow; standalone dispatch runs one target.

The provider RPMs are correctly named `ecr-credential-provider`,
`acr-credential-provider`, and `gcr-credential-provider`; their RPM metadata
provides the three `ose-*` capabilities requested by the 4.20 manifest. The
pinned upstream compose script's repository allowlist excludes these actual
package names, so the workflow extends that allowlist in its temporary
`openshift/os` checkout before composing; it leaves the RPM names and manifest
unchanged.

## CI context and source links

At the pinned commit, [`openshift/release`'s 4.22 config](https://github.com/openshift/release/blob/06c6fdbe105cccc2e7a06d4dd23cae71b8caaeda/ci-operator/config/openshift/os/openshift-os-release-4.22.yaml)
maps a `rhel-coreos-base:9.8` input to the Containerfile's `c9s-coreos` alias
and sets `OPENSHIFT_CI=1`. This is an internal ci-operator build, not a public
local-build recipe. Its generated Prow job uses registry pull/push and
reporting credentials. The checked
[`master` OKD SCOS config](https://github.com/openshift/release/blob/06c6fdbe105cccc2e7a06d4dd23cae71b8caaeda/ci-operator/config/openshift/os/openshift-os-master__okd-scos.yaml)
instead uses `stream-coreos-base:10` for its `stream-coreos` build; it does not
validate this pinned c9s base.
The upstream [`README`](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/README.md)
describes `stream-coreos` as the final image in the release payload. For more
background on how this repository produces the base image, see
[`docs/discovery/os.md`](docs/discovery/os.md) and
[`.github/workflows/build-scos-base.yml`](.github/workflows/build-scos-base.yml).
