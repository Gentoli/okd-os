# RPM mirror branches and compatibility patches

`rpms/mirror-plan.json` defines build targets and source-branch patterns. Mirror
metadata is stored in `.rpm-mirror.json` on the corresponding mirror branch,
not on `main`. `scan-okd-releases.yml` resolves and updates sources before it
composes release build configurations and calls
`build-okd-stream-coreos.yml`. That reusable image workflow receives resolved
source URLs and branches; each source must already exist upstream or in this
repository. It does not plan or probe RPM sources.

## Mirror branch layout

Mirror projects in this repository only when the CentOS Cloud SIG does not
provide the exact source branch needed by a build. Use the source patterns in
`rpms/mirror-plan.json`; do not add version/EL-specific source-map entries.
Use `rpms/<project>-<el>-<okd-version>` when the source is
OKD-release-specific and `rpms/<project>-<el>` when it is shared across OKD
releases. Never force-push a mirror branch.

`scan-okd-releases.yml` plans the release matrix first, then passes only the
selected OKD/EL and package combinations in the caller's matrix of reusable
`prepare-rpm-sources.yml` calls. Each call selects the exact upstream branch
when it exists, otherwise the configured fallback/shared branch and a local
mirror branch. It checks mirror branch existence; for an existing mirror, it
compares the upstream head SHA with the `source_sha` recorded in the branch's
`.rpm-mirror.json` to decide whether an update is needed. This SHA comparison
is solely the mirror freshness check; branch selection is based on branch
availability. No RPM `Release:` value is checked or assumed deterministic.

When a mirror needs setup or an update, `sync-rpm-mirror.yml` fetches the
upstream and mirror refs and provides them as remotes in a worktree. Copilot
compares the refs and maintains only the package spec and `.rpm-mirror.json`.
For CRI-O EL9, it preserves the `containernetworking-plugins` suggestion and
`%{_libexecdir}/cni` plugin directory. The workflow verifies the metadata and
allowed file set, stages the changes, then creates and publishes signed commits
through `push-signed-commits`; the agent does not commit or push. A new mirror
branch is initialized from the selected upstream branch. Do not modify other
files, reset, or force-push a mirror branch.

The metadata records `project`, `target_el`, `target_version`, `source_url`,
`source_branch`, `spec`, and `source_sha`. A later source SHA mismatch triggers
the agent to reconcile the mirror spec to the current upstream source.
`scan-okd-releases.yml` collects the per-call source artifacts before composing
release build configurations; its build matrix calls the reusable image
workflow once per release target. `reproduce-rpm-build.yml` is the manual
RPM-build entry point and also owns the package matrix. The sync job has
`contents: write` and `copilot-requests: write`; Copilot uses `gpt-6-luna`,
long context, and maximum reasoning effort. The organization must allow Copilot
CLI requests billed to the organization.

`conmon-rs` uses the shared EL9 source branch `c9s-sig-cloud` and mirror
`rpms/conmon-rs-el9` because CentOS Cloud has no OKD-release-specific c9s
branch.

## CRI-O EL9 compatibility patch

Compare the CentOS SIG's
[4.20 EL9 and EL10 branches](https://gitlab.com/CentOS/cloud/rpms/cri-o/-/compare/c9s-sig-cloud-okd-4.20...c10s-sig-cloud-okd-4.20).
The EL9 spec retains a `Suggests` for `containernetworking-plugins` and passes
`%{_libexecdir}/cni` as an additional CNI plugin directory when generating the
default CRI-O configuration. The EL10 spec drops those EL9-specific settings.
Both branches use the same RHEL `<= 10` Go build path, so this comparison does
not identify a build-only fix.

For the 4.22/EL9 mirror, preserve the EL9 CNI dependency and plugin-directory
settings while using the available 4.22 EL10 source branch. The reference patch
is [`rpm-patches/cri-o-el9.patch`](../rpm-patches/cri-o-el9.patch). When
upstream changes overlap the patch, recreate it against the updated spec and
preserve unrelated upstream changes. Do not add a compatibility change to
another package unless its source actually needs one for the target EL.

## Reproduce the EL9 build locally

Run these commands in CentOS Stream 9 after the mirror branch has been
published:

```bash
dnf install -y epel-release dnf-plugins-core epel-next-release
dnf config-manager --set-enabled crb
dnf makecache
dnf install -y centpkg-sig gcc gcc-c++ git go-rpm-macros golang make rpm-build

git clone --depth 1 --single-branch \
  --branch rpms/cri-o-el9-4.22 \
  https://github.com/Gentoli/okd-os.git cri-o
cd cri-o
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

Check the RPM identity with
`rpm -qp --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' <rpm-file>`; the
release should include `fallback.source_1.35.5_package_cri_o_target_4.22`.
