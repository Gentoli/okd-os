# Building the OKD node image from the published SCOS base

This research follows [`openshift/os` at
`3d00d375d491de94fd9dcd0b5440a0efbec3d9db`](https://github.com/openshift/os/tree/3d00d375d491de94fd9dcd0b5440a0efbec3d9db)
and uses the public base image
[`ghcr.io/gentoli/okd-os-scos-base:c9s`](https://github.com/Gentoli/okd-os/pkgs/container/okd-os-scos-base/1299816057?tag=c9s).

## What this build produces

`openshift/os` builds the final SCOS/OKD node image (`stream-coreos`) by adding
OpenShift packages to an existing CoreOS base. It does not build the base image
or compile the RPMs. The base comes from `coreos/rhel-coreos-config`; the
`openshift/os` build composes already-published RPMs into the final OSTree-based
container image. The optional extensions image is a separate build.

This repository's `c9s` image is a suitable public base input for that process:
an anonymous `skopeo inspect` returned digest
`sha256:27818dd2e0f2097df2e6a9c5518ae737a939d416e3f3a352f26fc05a2c1331d1`,
architecture `amd64`, `com.coreos.osname=scos`, and `com.coreos.stream=c9s`.
Running it confirmed `ID=centos`, `VERSION_ID=9`, and
`VERSION="9.0.20260926-dev0"`. Thus the compose script selects the `centos-9`
package set. The public image removes the need for an OpenShift pull secret just
to obtain the base; it does not provide the OpenShift RPM repositories.

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
for this snapshot. The upstream guide notes that its example version details
may be stale.

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
  --from ghcr.io/gentoli/okd-os-scos-base:c9s \
  --secret id=yumrepos,src=/path/to/all.repo \
  -v /etc/pki/ca-trust:/etc/pki/ca-trust:ro \
  --security-opt label=disable \
  -t localhost/stream-coreos:4.22
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
`--from ghcr.io/gentoli/okd-os-scos-base:c9s`. The first attempt stopped before
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

## CI context and source links

At the pinned commit, [`openshift/release`'s 4.22 config](https://github.com/openshift/release/blob/06c6fdbe105cccc2e7a06d4dd23cae71b8caaeda/ci-operator/config/openshift/os/openshift-os-release-4.22.yaml)
maps the `c9s-coreos` input to the node-image build and sets `OPENSHIFT_CI=1`.
The upstream [`README`](https://github.com/openshift/os/blob/3d00d375d491de94fd9dcd0b5440a0efbec3d9db/README.md)
describes `stream-coreos` as the final image in the release payload. For more
background on how this repository produces the base image, see
[`docs/discovery/os.md`](docs/discovery/os.md) and
[`.github/workflows/build-scos-base.yml`](.github/workflows/build-scos-base.yml).
