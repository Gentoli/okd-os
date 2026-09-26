# How OpenShift CI builds RPMs

This documents the RPM-producing paths found in OpenShift's [`openshift/release` ci-operator configuration](https://github.com/openshift/release/tree/master/ci-operator/config) for the six components in this repository's [RPM build matrix](../../.github/workflows/rpm-build.yml). An upstream RPM spec or Makefile target alone does not mean OpenShift CI builds that component as an RPM: the ci-operator configuration must connect a job to RPM build commands and artifacts.

## Components with OpenShift CI RPM builds

### Kubernetes (`openshift`)

The [Kubernetes CI configuration](https://github.com/openshift/release/blob/master/ci-operator/config/openshift/kubernetes/openshift-kubernetes-master.yaml) sets `rpm_build_commands: openshift-hack/build-rpms.sh`. That [build script](https://github.com/openshift/kubernetes/blob/master/openshift-hack/build-rpms.sh) finds the spec in the checkout and runs `rpmbuild` with the OpenShift build metadata. The upstream [`openshift.spec`](https://github.com/openshift/kubernetes/blob/master/openshift.spec) uses the project Makefile to build and package kube-apiserver, kube-controller-manager, kube-scheduler, kubelet, and hyperkube. The script documents RPM output under `_output/releases` and creates repository metadata for the generated RPMs.

### CRI-O (`cri-o`)

The [CRI-O CI configuration](https://github.com/openshift/release/blob/master/ci-operator/config/cri-o/cri-o/cri-o-cri-o-main.yaml) sets `rpm_build_commands: hack/build-rpms.sh`. The [script](https://github.com/cri-o/cri-o/blob/main/hack/build-rpms.sh) selects the spec under `contrib/test/ci`, resolves its build dependencies, and runs `rpmbuild`. The [spec](https://github.com/cri-o/cri-o/blob/main/contrib/test/ci/cri-o.spec) explicitly says it is for CI testing, not a distro package. The CI config then downloads the newly built `cri-o` RPM from its `built` repository and installs it into RHCOS test images.

### oc (`oc`)

The [oc CI configuration](https://github.com/openshift/release/blob/master/ci-operator/config/openshift/oc/openshift-oc-main.yaml) defines `rpm_build_commands` inline. It stages a source tarball and upstream [`oc.spec`](https://github.com/openshift/oc/blob/main/oc.spec) in `_rpmbuild`, runs `rpmbuild -ba`, and sets `rpm_build_location` to `_rpmbuild/RPMS/`. Promotion maps the resulting `rpms` image to `oc-rpms`. OpenShift's [oc RPM flow notes](https://github.com/openshift/release/blob/master/ci-operator/config/openshift/oc/README.md) explain that the Origin build merges `oc-rpms` with its own RPM artifacts into the `artifacts` image; see also the [Origin CI configuration](https://github.com/openshift/release/blob/master/ci-operator/config/openshift/origin/openshift-origin-main.yaml).

## Components without a configured OpenShift CI RPM path

The current `openshift/release` ci-operator configs do not show a component RPM build for these three matrix jobs. Their RPMs in this repository's GitHub Actions workflow are reproductions, not outputs of an identified OpenShift CI RPM job.

### cri-tools

No `rpm_build_commands` config or upstream RPM spec was found for `kubernetes-sigs/cri-tools`. Its upstream project supplies a `make binaries` build; this repository's [local spec template](../../.github/rpm-specs/cri-tools.spec.in) packages the resulting `crictl` and `critest` binaries with `rpmbuild`.

### conmon-rs

No component RPM build config was found for `containers/conmon-rs` in `openshift/release`. Its upstream [`make rpm` target](https://github.com/containers/conmon-rs/blob/main/Makefile) invokes `rpkg local`; that is not the `rpmbuild` path used by the OpenShift Kubernetes and CRI-O CI scripts. This repository instead uses its [local spec template](../../.github/rpm-specs/conmon-rs.spec.in) to package the upstream release build with `rpmbuild`.

### CRI-O credential provider

The upstream [repository includes `crio-credential-provider.spec`](https://github.com/openshift/crio-credential-provider/blob/main/crio-credential-provider.spec), which describes building and installing the Go binary. However, no corresponding RPM build entry was found in the current OpenShift ci-operator configuration. The GitHub Actions matrix builds this upstream spec directly.

## How this relates to this repository's workflow

The [local workflow](../../.github/workflows/rpm-build.yml) checks out each upstream source and either runs its OpenShift-style build script, builds an upstream spec, or uses a local spec template when no usable upstream RPM recipe exists. It reproduces package creation on CentOS Stream 9; it does not reproduce ci-operator image promotion or Origin's artifact aggregation. OpenShift's Kubernetes and CRI-O RPM scripts use `rpmbuild` and `createrepo`, not `rpkg`; the conmon-rs Makefile's separate `rpkg local` target is why its local reproduction uses a spec template instead.
