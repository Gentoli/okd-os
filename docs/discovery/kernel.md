# Kernel build discovery

## RPM build workflow failure

Run [36077081440](https://github.com/Gentoli/okd-os/actions/runs/36077081440) failed in the `Install Git and Toolchain` step for all six matrix jobs, before checkout or any RPM build started. CentOS Stream 9 DNF reported:

```text
No match for argument: rpkg
Error: Unable to find a match: rpkg
```

The workflow installed `rpkg` alongside the RPM build tools, but it is not available from the enabled CentOS Stream 9 and EPEL repositories. Removing it lets the package installation proceed.

I reproduced the failure in a CentOS Stream 9 container with the workflow's commands:

```sh
dnf install -y dnf-plugins-core epel-release epel-next-release
dnf config-manager --set-enabled crb
dnf makecache
dnf install -y git rpm-build rsync createrepo gcc gcc-c++ make golang krb5-devel bsdtar systemd cargo findutils rpkg
```

The last command fails because `rpkg` cannot be resolved. The same install command without `rpkg` is the corrected workflow command.

Upstream [`openshift/kubernetes`'s `openshift-hack/build-rpms.sh`](https://github.com/openshift/kubernetes/blob/master/openshift-hack/build-rpms.sh) checks for `rpmbuild` and `createrepo`; it does not require `rpkg`. The script explains that its RPM build runs through the upstream Makefile invoked by the spec file.

## Remaining component failures

Run [36220445413](https://github.com/Gentoli/okd-os/actions/runs/36220445413) confirmed the Kubernetes RPM built, but five other matrix jobs failed:

- CRI-O received an empty `OS_GIT_VERSION`: a shallow checkout has no tags, and the previous `git describe | sed || echo` pipeline succeeded with empty output. The workflow now falls back to a valid version and reads CRI-O's version from `internal/version/version.go`.
- `cri-tools` has a `make binaries` target but no RPM target or spec in its upstream repository. Its current `go.mod` requires Go 1.27, while the EL9 Go package defaults to `GOTOOLCHAIN=local`; the workflow now enables automatic Go toolchain selection. `conmon-rs`'s [upstream `make rpm` target](https://github.com/containers/conmon-rs/blob/main/Makefile) invokes `rpkg local`. The EL9 `python3-rpkg` package contains the Python library but does not install the `rpkg` executable. Local RPM spec templates now build both upstream projects with `rpmbuild`; the conmon version comes from its Cargo manifest.
- The `oc` and CRI-O credential-provider fallback commands created the source archive under `_rpmbuild` while archiving the whole checkout. Tar then read the archive while it was being written. Excluding `_rpmbuild` and `_output` prevents generated files from entering their source archives. Manual spec builds now use the spec's own version so the source archive and spec stay aligned.
- The subsequent run showed two further manual-spec issues: the `oc` spec's `os_git_vars` macro defaulted to empty, leaving `hack/generate-versioninfo.sh` without its required semantic version; and the credential-provider spec declares `Source0: %{name}.tar.gz`, not a versioned tarball. The workflow now passes its exported build metadata into `os_git_vars` and names the generated source archive from the spec's resolved `Source0`.

The workflow's CentOS Stream 9 and EPEL repositories provide the conmon build requirements (`capnproto` and `protobuf-compiler`) through `dnf builddep` on its spec.
