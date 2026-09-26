# How OpenShift CI and CentOS Cloud SIG build RPMs

This documents the RPM-producing paths found for the six components in this repository's [RPM build matrix](../../.github/workflows/rpm-build.yml). OpenShift's [`openshift/release` ci-operator configuration](https://github.com/openshift/release/tree/master/ci-operator/config) and the CentOS Cloud SIG's OKD package builds are separate pipelines; an upstream RPM spec alone does not identify which pipeline produced a package.

## Components with OpenShift CI RPM builds

### Kubernetes (`openshift`)

The [Kubernetes CI configuration](https://github.com/openshift/release/blob/master/ci-operator/config/openshift/kubernetes/openshift-kubernetes-master.yaml) sets `rpm_build_commands: openshift-hack/build-rpms.sh`. That [build script](https://github.com/openshift/kubernetes/blob/master/openshift-hack/build-rpms.sh) finds the spec in the checkout and runs `rpmbuild` with the OpenShift build metadata. The upstream [`openshift.spec`](https://github.com/openshift/kubernetes/blob/master/openshift.spec) uses the project Makefile to build and package kube-apiserver, kube-controller-manager, kube-scheduler, kubelet, and hyperkube. The script documents RPM output under `_output/releases` and creates repository metadata for the generated RPMs.

### CRI-O (`cri-o`)

The [CRI-O CI configuration](https://github.com/openshift/release/blob/master/ci-operator/config/cri-o/cri-o/cri-o-cri-o-main.yaml) sets `rpm_build_commands: hack/build-rpms.sh`. The [script](https://github.com/cri-o/cri-o/blob/main/hack/build-rpms.sh) selects the spec under `contrib/test/ci`, resolves its build dependencies, and runs `rpmbuild`. The [spec](https://github.com/cri-o/cri-o/blob/main/contrib/test/ci/cri-o.spec) explicitly says it is for CI testing, not a distro package. The CI config then downloads the newly built `cri-o` RPM from its `built` repository and installs it into RHCOS test images. Separately, the CentOS Cloud SIG builds a distributable CRI-O RPM for OKD as described below.

### oc (`oc`)

The [oc CI configuration](https://github.com/openshift/release/blob/master/ci-operator/config/openshift/oc/openshift-oc-main.yaml) defines `rpm_build_commands` inline. It stages a source tarball and upstream [`oc.spec`](https://github.com/openshift/oc/blob/main/oc.spec) in `_rpmbuild`, runs `rpmbuild -ba`, and sets `rpm_build_location` to `_rpmbuild/RPMS/`. Promotion maps the resulting `rpms` image to `oc-rpms`. OpenShift's [oc RPM flow notes](https://github.com/openshift/release/blob/master/ci-operator/config/openshift/oc/README.md) explain that the Origin build merges `oc-rpms` with its own RPM artifacts into the `artifacts` image; see also the [Origin CI configuration](https://github.com/openshift/release/blob/master/ci-operator/config/openshift/origin/openshift-origin-main.yaml).

## Components without a configured OpenShift CI RPM path

The current `openshift/release` ci-operator configs do not show component RPM jobs for these three matrix jobs. This does not mean no other project builds them as RPMs: the CentOS Cloud SIG packages `cri-tools` and `conmon-rs` for OKD through its own CentOS Build System (CBS) pipeline, described below.

### cri-tools

No `rpm_build_commands` config or RPM spec was found in the upstream `kubernetes-sigs/cri-tools` source repository. The CentOS Cloud SIG maintains a separate [OKD 4.17 package spec](https://gitlab.com/CentOS/archives/git.centos.org/rpms/cri-tools/-/blob/7b28920bb080d3c72fc4939152f343cbb368cdf8/SPECS/cri-tools.spec) on the `c9s-sig-cloud-okd-4.17` branch. It builds version 1.30.1 from the upstream release tarball using RPM Go macros, generates the `crictl` man page, and installs `crictl` (not `critest`). The package is built for the `cloud9s-okd-4.17-el9s` CBS target and promoted through the candidate/testing/release tags. The local [fallback spec](../../.github/rpm-specs/cri-tools.spec.in) in this repository instead runs `make binaries` and packages both `crictl` and `critest`.

### conmon-rs

No component RPM build config was found for `containers/conmon-rs` in `openshift/release`. The CentOS Cloud SIG maintains a [separate spec](https://gitlab.com/CentOS/archives/git.centos.org/rpms/conmon-rs/-/blob/070ba9e0ee79144b3a8ae1fe605c8ce561581c43/SPECS/conmon-rs.spec) on the shared `c9s-sig-cloud` branch. It packages version 0.5.1 from upstream release and vendor tarballs, runs `make release`, and installs `conmonrs`. The CentOS OKD packaging notes associate it with the `cloud9s-okd-<VERSION>-el9s` CBS target and candidate/testing/release tags. This spec and CBS build are distinct from the upstream [`make rpm` target](https://github.com/containers/conmon-rs/blob/main/Makefile), which invokes `rpkg local`, and from this repository's [local spec template](../../.github/rpm-specs/conmon-rs.spec.in).

### CRI-O credential provider

The upstream [repository includes `crio-credential-provider.spec`](https://github.com/openshift/crio-credential-provider/blob/main/crio-credential-provider.spec), which describes building and installing the Go binary. No corresponding RPM build entry was found in the current OpenShift ci-operator configuration, and no credential-provider RPM appears in the linked CentOS OKD 4.17 package/SRPM listing. The GitHub Actions matrix builds this upstream spec directly.

## CentOS Stream 9 Cloud SIG repository for OKD 4.17

The [CentOS buildlogs listing](https://buildlogs.centos.org/centos/9-stream/cloud/aarch64/okd-4.17/Packages/c/) contains `cri-o-1.30.6-1.el9s`, `cri-tools-1.30.1-1.el9s`, and `conmon-rs-0.5.1-1.el9s` for aarch64. Matching source RPMs are listed in the [OKD 4.17 source repository](https://mirror.stream.centos.org/SIGs/9-stream/cloud/source/okd-4.17/Packages/c/). The buildlogs page warns it contains a mix of raw/unsigned artifacts for testing; the corresponding published repository is under [CentOS Stream 9 Cloud SIG](https://mirror.stream.centos.org/SIGs/9-stream/cloud/aarch64/okd-4.17/).

These are CentOS Stream 9-targeted (`.el9s`) packages, but they are not generic packages from the CentOS Stream base distribution. They are OKD-specific packages maintained by the [CentOS Cloud SIG](https://sigs.centos.org/cloud/), using package specs in CentOS SIG dist-git and the [CentOS Build System (CBS/Koji)](https://sigs.centos.org/guide/cbs/). The SIG's [OKD RPM working notes](https://hackmd.io/@lorbus/SywpTz2r2) give the build target as `cloud9s-okd-<VERSION>-el9s`, with candidate, testing, and release tags, and document submitting builds from the package Git repository and commit. For OKD 4.17 this corresponds to the `cloud9s-okd-4.17-el9s` target.

### CRI-O CBS package definition

The OKD 4.17 [CentOS SIG spec](https://gitlab.com/CentOS/archives/git.centos.org/rpms/cri-o/-/blob/ad4d6df81ca3004077528539a82bb8cd6b6ead66/SPECS/cri-o.spec) pins version 1.30.6 and an upstream source commit, builds CRI-O's Go commands plus `pinns`, creates the man pages, and installs the daemon, config, and systemd units. This CBS package definition is separate from the CI-only spec and script used by OpenShift ci-operator above.

## How this relates to this repository's workflow

The [local workflow](../../.github/workflows/rpm-build.yml) checks out upstream sources and either runs an OpenShift-style build script, builds an upstream spec, or uses a local spec template. It reproduces package creation on CentOS Stream 9; it does not reproduce OpenShift ci-operator image promotion or CBS package promotion. In particular, the CentOS SIG definitions are distinct downstream packaging recipes: the local `cri-tools` template includes `critest`, and the local `conmon-rs` template builds the checked-out source rather than the SIG's pinned release and vendor tarballs. OpenShift's Kubernetes and CRI-O RPM scripts use `rpmbuild` and `createrepo`; `rpkg local` is only the separate upstream conmon-rs Makefile target, not the CentOS CBS package build.
