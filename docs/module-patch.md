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
releases. Keep the full upstream history as the base; do not squash or
force-push updates.

The first commit after the upstream base is an empty commit whose subject
identifies the source branch:

```text
PATCH/<upstream-branch-name>
```

Its body contains the deterministic patch ID
`source_<source-version>_package_<rpm-name>_target_<target-version>`. Replace
characters outside letters, digits, periods, and underscores with underscores.
For example, the CRI-O 4.22/EL9 mirror uses
`source_1.35.5_package_cri_o_target_4.22`.
Each mirrored spec carries `.fallback.<patch-id>` in its `Release:` value,
before `%{?dist}`. The mirror workflow updates this deterministic release patch
for every mirrored package, even when no additional functional EL
compatibility change is needed; the RPM build only consumes the prepared spec.

`scan-okd-releases.yml` plans the release matrix first, then passes only the
selected OKD/EL target combinations to the reusable
`prepare-rpm-sources.yml` workflow. That workflow expands a package-by-target
matrix, checks exact upstream branches and mirror freshness using Git's
patch-equivalence check, and collects stale mirrors for one
`sync-rpm-mirror.yml` call. It then resolves each package source in the same
matrix and combines the results for the caller. Shared mirror branches are
deduplicated before synchronization. The scan composes release build
configurations with these resolved sources; its build matrix calls the
reusable image workflow once per release target. `reproduce-rpm-build.yml` is
the manual RPM-build entry point and uses the same preparation workflow.
The sync workflow uses a single job: a GitHub Script step
creates mirror worktrees and metadata, Copilot CLI replays missing commits and
recreates the documented package patch using
`.github/prompts/rpm-mirror-maintenance.md`, and the workflow publishes commits
with `push-signed-commits`. The job has `contents: write` and
`copilot-requests: write`. Copilot uses `gpt-6-luna`, long context, and maximum
reasoning effort. The organization must allow Copilot CLI requests billed to
the organization. A new mirror branch is seeded with the upstream tip before
the workflow's signed marker and compatibility commits are published.
Copilot has file-write access but no shell access. Before signing, the workflow
checks that the spec exactly matches the source plus the deterministic Release
suffix and, for CRI-O EL9, only the documented CNI additions; it also rejects
unexpected files or changed branch metadata.

Updates append cherry-picked upstream changes to the mirror, retaining each
change's patch equivalence. The branch-local `.rpm-mirror.json` records the
upstream URL/branch, target EL/version, spec path, and current source revision.
Never reset or force-push a mirror branch. The first `PATCH/` marker remains
unchanged after later upstream updates.

`conmon-rs` does need the shared EL9 mirror `rpms/conmon-rs-el9` under this
branch-maintenance policy: CentOS Cloud has `c9s-sig-cloud` but no
OKD-release-specific c9s branch. Use that shared branch as the mirror base and
the `el9` target component in its patch ID. The mirror keeps source metadata
and the deterministic release patch local to the branch; it is not needed
because the upstream shared spec is otherwise unbuildable.

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
