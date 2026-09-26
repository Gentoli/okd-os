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
