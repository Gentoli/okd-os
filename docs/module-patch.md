# RPM mirror branches and compatibility patches

`rpms/mirror-plan.json` defines build targets and source-branch patterns. Mirror
metadata is stored in `.rpm-mirror.json` on the corresponding mirror branch,
not on `main`. Source selection runs before the reusable `rpm-build.yml`
workflow; the RPM build receives resolved URLs and branch names and does not
probe upstream branches or synthesize fallback patches.

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

The read-only planner in `plan-rpm-mirrors.yml` requests only an OKD version.
For that version it checks exact upstream branches and existing mirrors using
Git's patch-equivalence check. It skips when direct source branches suffice or
all mirrors are current; otherwise it dispatches one version-scoped
`sync-rpm-mirror.yml` run. The sync workflow seeds missing branches from their
selected upstream tips, asks Copilot CLI to replay missing commits and recreate
the documented package patch, and publishes resulting commits with
`pgaskin/push-signed-commits`. Copilot has repository read access and
`copilot-requests: write`; only the publishing job has repository write access.
The CLI uses `gpt-6-luna@max` with the long-context tier. The organization must
allow Copilot CLI requests billed to the organization. The workflow requests
the 1M context tier and maximum reasoning effort.

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
