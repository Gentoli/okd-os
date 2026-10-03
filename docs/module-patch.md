# Building the OKD 4.22 CRI-O RPM for EL9

The 4.22/EL9 image build can select an RPM artifact run that has no CRI-O
package. The CentOS Cloud SIG has a `c10s-sig-cloud-okd-4.22` CRI-O package
branch, but no matching `c9s-sig-cloud-okd-4.22` branch. The RPM workflow
therefore builds the EL9 package from the 4.22 EL10 spec with the small
compatibility patch in [`rpm-patches/cri-o-el9.patch`](../rpm-patches/cri-o-el9.patch).

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

The `rpm-build.yml` workflow uses `c10s-sig-cloud-okd-4.22` only for the
4.22/EL9 CRI-O build, applies this patch before fetching lookaside sources, and
builds it in the EL9 container. Other components and the 4.22/EL10 build keep
their existing source branches and specs.

## Reproduce the EL9 build locally

Run these commands in CentOS Stream 9, from a clean working directory. The
final `rpmbuild` invocation matches the workflow's local build.

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

The resulting RPM should be an EL9 build of CRI-O 1.35.5. Check the output
with `rpm -qp --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' <rpm-file>`.
