# How OpenShift CI and CentOS Cloud SIG build RPMs

This documents the RPM-producing paths found for the six components in this repository's [RPM build matrix](../../.github/workflows/rpm-build.yml). OpenShift's [`openshift/release` ci-operator configuration](https://github.com/openshift/release/tree/b408f33c954929bf933101fa64895c6fbca38ebe/ci-operator/config) and the CentOS Cloud SIG's OKD package builds are separate pipelines; an upstream RPM spec alone does not identify which pipeline produced a package. Repository-file links use commit-pinned permalinks.

## Components with OpenShift CI RPM builds

### Kubernetes (`openshift`)

The [Kubernetes CI configuration](https://github.com/openshift/release/blob/b408f33c954929bf933101fa64895c6fbca38ebe/ci-operator/config/openshift/kubernetes/openshift-kubernetes-master.yaml) sets `rpm_build_commands: openshift-hack/build-rpms.sh`. That [build script](https://github.com/openshift/kubernetes/blob/a3efef04229b38cc7d480d848e1d3b0c9c298531/openshift-hack/build-rpms.sh) finds the spec in the checkout and runs `rpmbuild` with the OpenShift build metadata. The upstream [`openshift.spec`](https://github.com/openshift/kubernetes/blob/a3efef04229b38cc7d480d848e1d3b0c9c298531/openshift.spec) uses the project Makefile to build and package kube-apiserver, kube-controller-manager, kube-scheduler, kubelet, and hyperkube. The script documents RPM output under `_output/releases` and creates repository metadata for the generated RPMs.

### CRI-O (`cri-o`)

The [CRI-O CI configuration](https://github.com/openshift/release/blob/b408f33c954929bf933101fa64895c6fbca38ebe/ci-operator/config/cri-o/cri-o/cri-o-cri-o-main.yaml) sets `rpm_build_commands: hack/build-rpms.sh`. The [script](https://github.com/cri-o/cri-o/blob/cc12ad82517d88424ba2a278d21a34f23f0f2e13/hack/build-rpms.sh) selects the spec under `contrib/test/ci`, resolves its build dependencies, and runs `rpmbuild`. The [spec](https://github.com/cri-o/cri-o/blob/cc12ad82517d88424ba2a278d21a34f23f0f2e13/contrib/test/ci/cri-o.spec) explicitly says it is for CI testing, not a distro package. The CI config then downloads the newly built `cri-o` RPM from its `built` repository and installs it into RHCOS test images. This repository's workflow separately builds the CentOS Cloud SIG's distributable CRI-O RPM for OKD through CBS.

### oc (`oc`)

The [oc CI configuration](https://github.com/openshift/release/blob/b408f33c954929bf933101fa64895c6fbca38ebe/ci-operator/config/openshift/oc/openshift-oc-main.yaml) defines `rpm_build_commands` inline. It stages a source tarball and upstream [`oc.spec`](https://github.com/openshift/oc/blob/641593714a8ee6fa26e2228901cfd37d4f5937c8/oc.spec) in `_rpmbuild`, runs `rpmbuild -ba`, and sets `rpm_build_location` to `_rpmbuild/RPMS/`. Promotion maps the resulting `rpms` image to `oc-rpms`. OpenShift's [oc RPM flow notes](https://github.com/openshift/release/blob/b408f33c954929bf933101fa64895c6fbca38ebe/ci-operator/config/openshift/oc/README.md) explain that the Origin build merges `oc-rpms` with its own RPM artifacts into the `artifacts` image; see also the [Origin CI configuration](https://github.com/openshift/release/blob/b408f33c954929bf933101fa64895c6fbca38ebe/ci-operator/config/openshift/origin/openshift-origin-main.yaml).

## Components without a configured OpenShift CI RPM path

The current `openshift/release` ci-operator configs do not show component RPM jobs for `cri-tools`, `conmon-rs`, or the CRI-O credential provider. This does not mean no other project builds them as RPMs: the CentOS Cloud SIG packages `cri-tools` and `conmon-rs` for OKD through its own CentOS Build System (CBS) pipeline, described below.

### cri-tools

No `rpm_build_commands` config or RPM spec was found in the upstream `kubernetes-sigs/cri-tools` source repository. The CentOS Cloud SIG maintains a separate [OKD 4.17 package spec](https://gitlab.com/CentOS/archives/git.centos.org/rpms/cri-tools/-/blob/7b28920bb080d3c72fc4939152f343cbb368cdf8/SPECS/cri-tools.spec) on the `c9s-sig-cloud-okd-4.17` branch. It builds version 1.30.1 from the upstream release tarball using RPM Go macros, generates the `crictl` man page, and installs `crictl` (not `critest`). The package is built for the `cloud9s-okd-4.17-el9s` CBS target and promoted through the candidate/testing/release tags. The workflow's CBS matrix uses the SIG's [`c9s-sig-cloud-okd-4.20` spec](https://gitlab.com/CentOS/cloud/rpms/cri-tools/-/blob/78ac0f0e3be1915e011f4941c8a7a996cad12586/SPECS/cri-tools.spec) as a scratch-build source.

### conmon-rs

No component RPM build config was found for `containers/conmon-rs` in `openshift/release`. The CentOS Cloud SIG maintains a [separate spec](https://gitlab.com/CentOS/archives/git.centos.org/rpms/conmon-rs/-/blob/070ba9e0ee79144b3a8ae1fe605c8ce561581c43/SPECS/conmon-rs.spec) on the shared `c9s-sig-cloud` branch. It packages version 0.5.1 from upstream release and vendor tarballs, runs `make release`, and installs `conmonrs`. The CentOS OKD packaging notes associate it with the `cloud9s-okd-<VERSION>-el9s` CBS target and candidate/testing/release tags. This spec and CBS build are distinct from the upstream [`make rpm` target](https://github.com/containers/conmon-rs/blob/247d7f397ee7a7bde8e5f4a1beb4bde98ff01e91/Makefile), which invokes `rpkg local`. The workflow's CBS matrix instead builds from the SIG's shared [`c9s-sig-cloud` branch](https://gitlab.com/CentOS/cloud/rpms/conmon-rs/-/blob/0d8cf8624ae66c19bad554c0207a2fd42341652b/SPECS/conmon-rs.spec).

### CRI-O credential provider

The upstream [repository includes `crio-credential-provider.spec`](https://github.com/openshift/crio-credential-provider/blob/83d4961cee137f764e5ef11b7b4301e0496dfa89/crio-credential-provider.spec), which describes building and installing the Go binary. No corresponding RPM build entry was found in the current OpenShift ci-operator configuration, and no credential-provider RPM appears in the linked CentOS OKD 4.17 package/SRPM listing. The GitHub Actions matrix builds this upstream spec directly.

## CentOS Stream 9 Cloud SIG repository for OKD 4.17

The [CentOS buildlogs listing](https://buildlogs.centos.org/centos/9-stream/cloud/aarch64/okd-4.17/Packages/c/) contains `cri-o-1.30.6-1.el9s`, `cri-tools-1.30.1-1.el9s`, and `conmon-rs-0.5.1-1.el9s` for aarch64. Matching source RPMs are listed in the [OKD 4.17 source repository](https://mirror.stream.centos.org/SIGs/9-stream/cloud/source/okd-4.17/Packages/c/). The buildlogs page warns it contains a mix of raw/unsigned artifacts for testing; the corresponding published repository is under [CentOS Stream 9 Cloud SIG](https://mirror.stream.centos.org/SIGs/9-stream/cloud/aarch64/okd-4.17/).

These are CentOS Stream 9-targeted (`.el9s`) packages, but they are not generic packages from the CentOS Stream base distribution. They are OKD-specific packages maintained by the [CentOS Cloud SIG](https://sigs.centos.org/cloud/), using package specs in CentOS SIG dist-git and the [CentOS Build System (CBS/Koji)](https://sigs.centos.org/guide/cbs/). The SIG's [OKD RPM working notes](https://hackmd.io/@lorbus/SywpTz2r2) give the build target as `cloud9s-okd-<VERSION>-el9s`, with candidate, testing, and release tags, and document submitting builds from the package Git repository and commit. For OKD 4.17 this corresponds to the `cloud9s-okd-4.17-el9s` target.

### CRI-O CBS package definition

The OKD 4.17 [CentOS SIG spec](https://gitlab.com/CentOS/archives/git.centos.org/rpms/cri-o/-/blob/ad4d6df81ca3004077528539a82bb8cd6b6ead66/SPECS/cri-o.spec) pins version 1.30.6 and an upstream source commit, builds CRI-O's Go commands plus `pinns`, creates the man pages, and installs the daemon, config, and systemd units. This CBS package definition is separate from the CI-only spec and script used by OpenShift ci-operator above.

## CentOS Stream 10 Cloud SIG builds for OKD 4.22 and 5.0

These are CentOS Cloud SIG downstream builds for OKD, not packages from the CentOS Stream base distribution. CBS/Koji build targets identify both the buildroot and the destination tag: the targets are `cloud10s-okd-4.22-el10s` and `cloud10s-okd-5.0-el10s`, with corresponding `-build` tags and `-candidate` destinations. The [CBS guide](https://sigs.centos.org/guide/cbs/) describes the build, candidate, testing, and release tag flow. Koji build records preserve the source Git commit, while the published `.el10s` RPMs and SRPMs appear in the CentOS Stream 10 OKD repositories linked below.

| OKD target | CRI-O | cri-tools | conmon-rs |
| --- | --- | --- | --- |
| 4.22 | `cri-o-1.35.5-1.el10s` ([CBS build 77149](https://cbs.centos.org/koji/buildinfo?buildID=77149)) | `cri-tools-1.35.0-1.el10s` ([CBS build 64985](https://cbs.centos.org/koji/buildinfo?buildID=64985)) | `conmon-rs-0.6.6-2.el10s` ([CBS build 57463](https://cbs.centos.org/koji/buildinfo?buildID=57463)) |
| 5.0 | `cri-o-1.36.4-1.el10s` ([CBS build 77997](https://cbs.centos.org/koji/buildinfo?buildID=77997)) | `cri-tools-1.36.0-1.el10s` ([CBS build 71122](https://cbs.centos.org/koji/buildinfo?buildID=71122)) | `conmon-rs-0.6.6-2.el10s` (same CBS build 57463) |

The corresponding package indexes contain the binaries and source RPMs: OKD [4.22 x86_64](https://mirror.stream.centos.org/SIGs/10-stream/cloud/x86_64/okd-4.22/Packages/c/) and [4.22 source](https://mirror.stream.centos.org/SIGs/10-stream/cloud/source/okd-4.22/Packages/c/); OKD [5.0 x86_64](https://mirror.stream.centos.org/SIGs/10-stream/cloud/x86_64/okd-5.0/Packages/c/) and [5.0 source](https://mirror.stream.centos.org/SIGs/10-stream/cloud/source/okd-5.0/Packages/c/). The CBS candidate, testing, and release tags contain the listed NVRs for both target releases; the conmon-rs build is shared.

### CRI-O

The `c10s-sig-cloud-okd-4.22` package branch's [spec at build commit `c67b10d`](https://gitlab.com/CentOS/cloud/rpms/cri-o/-/blob/c67b10debe9270164d2cbb0bad0a2a1aae12d019/SPECS/cri-o.spec) builds version 1.35.5; the `c10s-sig-cloud-okd-5.0` [spec at build commit `e2b01d1`](https://gitlab.com/CentOS/cloud/rpms/cri-o/-/blob/e2b01d11dc9de73387652a8a1d03ea204ffd3e26/SPECS/cri-o.spec) builds version 1.36.4. For EL10, the recipe uses Go's vendor mode, builds the Go commands and `pinns`, generates documentation/man pages, and installs CRI-O configuration, completions, and systemd units.

### cri-tools

For OKD 4.22, CBS records build 64985 from package commit [`f05e539`](https://gitlab.com/CentOS/cloud/rpms/cri-tools/-/blob/f05e5397c3a0198518a473a8f3f612e9bc1c00d3/SPECS/cri-tools.spec), which sets version 1.35.0. For OKD 5.0, build 71122 uses commit [`b9edf4a`](https://gitlab.com/CentOS/cloud/rpms/cri-tools/-/blob/b9edf4a0f17d3a60017d54c5d6f6874d6d01a142/SPECS/cri-tools.spec), version 1.36.0. Both recipes use Go RPM macros and vendored sources to build `crictl` only (not `critest`), then install its man page and bash completion.

### conmon-rs

Both targets currently tag the same CBS build, `conmon-rs-0.6.6-2.el10s`. Its exact [CentOS dist-git spec at source commit `318cb8e`](https://gitlab.com/CentOS/archives/git.centos.org/rpms/conmon-rs/-/blob/318cb8e1929511bf4b3502fcb4a587d654031776/SPECS/conmon-rs.spec) uses the upstream release tarball, runs `make release`, and installs `conmonrs`. A newer [Cloud SIG recipe at commit `557f9ec`](https://gitlab.com/CentOS/cloud/rpms/conmon-rs/-/blob/557f9ec114ecedc4f4715c62f2d359f01aaf5bf9/SPECS/conmon-rs.spec) specifies version 0.7.1, but that NVR is not in either target's CBS candidate/testing/release tags or the current mirror listings checked on 2026-09-26.

## How this relates to this repository's workflow

The [RPM workflow](../../.github/workflows/rpm-build.yml) has two separate matrices, both running on CentOS Stream 9. `build-rpms` builds checked-out upstream `.spec` files (Kubernetes, oc, and the CRI-O credential provider). `build-rpms-centos-sig` uses the CentOS SIG's CRI-O and cri-tools `c9s-sig-cloud-okd-4.20` branches and conmon-rs `c9s-sig-cloud` branch as local package sources. It downloads the listed lookaside sources with `centpkg-sig sources`, installs build dependencies, runs `rpmbuild` locally, and uploads the resulting RPMs only as GitHub Actions artifacts. It does not submit a CBS/Koji task or upload/push any build or artifact to CentOS infrastructure, and requires no CBS credentials. The CentOS SIG definitions remain downstream packaging recipes; `rpkg local` is only the separate upstream conmon-rs Makefile target.
