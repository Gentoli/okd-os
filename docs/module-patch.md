# Building the OKD 4.22 CRI-O RPM for EL9

The CentOS Cloud SIG has 4.22 package branches for EL10, but no matching
`c9s-sig-cloud-okd-4.22` branches for the EL9 target. The RPM workflow first
checks for a matching package/target-OS branch, then falls back to a matching
target-version branch from another stream or a shared stream branch.

## Why the patch is needed

Compare the CentOS SIG's [4.20 EL9 and EL10 branches](https://gitlab.com/CentOS/cloud/rpms/cri-o/-/compare/c9s-sig-cloud-okd-4.20...c10s-sig-cloud-okd-4.20).
The EL9 spec retains a `Suggests` for `containernetworking-plugins` and passes
`%{_libexecdir}/cni` as an additional CNI plugin directory when generating the
default CRI-O configuration. The EL10 spec drops those EL9-specific settings.
Both branches use the same RHEL `<= 10` Go build path, so this diff does not
identify a build-only fix. The missing 4.22/EL9 RPM is addressed by building
from the available 4.22 EL10 branch in an EL9 environment; this patch restores
the two EL9 CNI dependency/configuration settings without reverting unrelated
version or source changes.

When it falls back, it synthesizes a spec patch for every package. The stable
patch ID is `source_<source-version>_package_<rpm-name>_target_<OKD-version>`
(non-RPM-safe characters are replaced with underscores). The patch appends
that ID to the RPM release, making fallback RPMs traceable and preventing
release collisions. Generated patches are saved under
`rpmbuild/<package>/PATCHES` and included with the SIG build artifact. For
4.22/EL9, the separate
[`cri-o-el9.patch`](../rpm-patches/cri-o-el9.patch) also restores the EL9 CNI
dependency and plugin path on the CRI-O spec. The SIG build is unconditional
and covers CRI-O, cri-tools, and conmon-rs.

## Reproduce the EL9 build locally

Run these commands in CentOS Stream 9, from a clean working directory. They
reproduce the CRI-O build. For a fallback source branch, the workflow also
stamps its generated patch ID into the RPM release.

```bash
dnf install -y epel-release dnf-plugins-core epel-next-release
dnf config-manager --set-enabled crb
dnf makecache
dnf install -y centpkg-sig gcc gcc-c++ git go-rpm-macros golang make rpm-build

git clone --depth 1 --single-branch \
  --branch c10s-sig-cloud-okd-4.22 \
  https://gitlab.com/CentOS/cloud/rpms/cri-o.git
cd cri-o
git apply /path/to/okd-os/rpm-patches/cri-o-el9.patch
centpkg-sig sources

spec=SPECS/cri-o.spec
topdir="$PWD/_rpmbuild"
mkdir -p "$topdir"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
while IFS= read -r filename; do
  source_file="$filename"
  if [ ! -f "$source_file" ] && [ -f "SOURCES/$filename" ]; then
    source_file="SOURCES/$filename"
  fi
  test -f "$source_file"
  cp "$source_file" "$topdir/SOURCES/"
done < <(sed -nE 's/^[^ ]+ \(([^)]+)\) = .*/\1/p' sources)
if [ -d SOURCES ]; then
  cp -a SOURCES/. "$topdir/SOURCES/"
fi

dnf builddep -y "$spec"
rpmbuild -ba "$spec" \
  --define "_topdir $topdir" \
  --define "_sourcedir $topdir/SOURCES"
find "$topdir/RPMS" -type f -name '*.rpm' -print
```

The resulting RPM should be an EL9 build of CRI-O 1.35.5. A fallback patch ID
for that source is
`source_1.35.5_package_cri_o_target_4.22`. Check the output with
`rpm -qp --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' <rpm-file>`.
