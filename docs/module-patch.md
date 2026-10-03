# RPM source mirrors and compatibility patches

`scan-okd-releases.yml` selects releases, prepares their package sources, then
composes build configurations. `reproduce-rpm-build.yml` uses the same source
preparation for a manually selected target. A successful preparation returns a
source URL and branch that already exist. RPM and image builds consume that
contract without probing fallback branches or applying compatibility patches.

## Branches and patch identity

`rpms/mirror-plan.json` describes exact, fallback, and shared source branches.
An exact target branch is used directly. A configured shared branch already
targeting the requested EL is also used directly when no exact branch exists.
For example, EL9 conmon-rs uses upstream `c9s-sig-cloud` for both 4.20 and 4.22;
it does not need a mirror or an identity commit. Compatibility fallback sources
use mirrors named `rpms/<project>-el<major>-<okd-version>`.

The mirror retains the selected upstream branch's complete history, separate
from `main`. The first commit after upstream has the subject
`PATCH/<upstream-base-branch>` and commits `.rpm-patch.json`. Its fields are
`id`, `project`, `source_url`, `source_branch`, `target_el`, and
`target_okd_version` (null for shared packages). The ID format is
`<project>__<source-branch>__el<target-major>-okd<target-version>`, or
`<project>__<source-branch>__el<target-major>` for a shared target. Source branch
names carry the source EL/OKD version. Neither SHAs nor RPM `Release:` values
form part of the identity.

Compatibility commits follow the identity commit. The workflow checks whether
the fetched upstream head is an ancestor of the mirror head to determine
freshness. Current mirrors skip the agent and publication steps.

## Generic creation and update recipe

1. Fetch the upstream base and the target mirror (if present). Inspect the
   packaging repository, its specs, `SOURCES`, the lookaside `sources` manifest,
   and recent history.
2. Identify comparable upstream branches for the source and target
   environments. Prefer the same OKD version in both; if absent, use a previous
   version available in both to understand packaging differences. Separate
   environment adaptations from changes to package versions, source archives,
   and unrelated upstream improvements.
3. Start a local branch at the current source base. Write `.rpm-patch.json`
   from the supplied context, and commit it with the required `PATCH/` subject.
   This commit records identity; compatibility changes follow it.
4. For creation, recreate only target differences justified by the comparison.
   For updates, find the old marker and its parent, then replay compatibility
   commits onto the current source with rebase or cherry-pick. Recreate the
   marker first. Resolve conflicts using current packaging, drop obsolete
   adaptations, and retain unrelated upstream changes. Include affected source
   files and lookaside manifests. Do not merge upstream history or copy its
   files into commits on the old mirror base.
5. Commit adaptations after the marker. An unaffected package still has an
   identity commit. Report all resulting patch-stack commit IDs, including the
   recreated marker. The agent must not push; workflow steps sign and publish.

The package-agnostic instruction is in
`.github/prompts/rpm-mirror-maintenance.md`. Sync uses one job with
`contents: write`, `copilot-requests: write`, inline `github-script`
preparation, and Copilot CLI with `--model gpt-6-luna`. There is no post-agent
content validation. The organization policy must permit
[Copilot CLI requests in Actions](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli-in-actions).

## Signed publication

The [signing action](https://github.com/pgaskin/push-signed-commits) recreates
commits and requires an existing destination branch. Sync seeds a unique
temporary publishing branch with the original upstream base, signs the agent's
marker and compatibility commits there, and fetches the signed result. It
updates only the mirror ref using an explicit force-with-lease against the
observed mirror head (or requiring absence on creation).

This permits rebased patches while retaining upstream commit IDs. A signing
failure leaves the mirror unchanged. Another writer causes the lease to reject
publication; rerun preparation against the new state. The temporary branch is
removed on success or failure. Concurrency is scoped to the mirror branch,
with queued calls for that branch. Native shared sources skip mirror sync.

## CRI-O EL9 example

Compare `c9s-sig-cloud-okd-4.20` and `c10s-sig-cloud-okd-4.20` in
[the upstream package repository](https://gitlab.com/CentOS/cloud/rpms/cri-o).
The EL9 spec retains `Suggests: containernetworking-plugins >= 1.0.0-1` and an
additional `%{_libexecdir}/cni` plugin directory when generating configuration.
The EL10 spec drops these settings. Its newer version and changelog are
unrelated to this adaptation.

For 4.22 EL9, start at `c10s-sig-cloud-okd-4.22`, create the identity commit,
then restore the two settings in a compatibility commit on the mirror branch.
Recreate that commit when upstream changes overlap it. The 4.20 `cri-tools`
EL9/EL10 specs are identical;
that comparison does not justify a speculative patch. The shared EL9
`conmon-rs` source is already target-specific.

## Reproduce a prepared package locally

Run in matching CentOS Stream. Replace the package and branch with the prepared
source map; this example uses the published CRI-O EL9 mirror:

```bash
dnf install -y epel-release dnf-plugins-core epel-next-release
dnf config-manager --set-enabled crb
dnf install -y centpkg-sig gcc gcc-c++ git go-rpm-macros golang make rpm-build
project=cri-o
git clone --single-branch --branch rpms/cri-o-el9-4.22 \
  https://github.com/Gentoli/okd-os.git "$project"
cd "$project"
centpkg-sig --name "$project" --namespace rpms sources
spec="SPECS/$project.spec"
topdir="$PWD/_rpmbuild"
mkdir -p "$topdir"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
while IFS= read -r filename; do
  source_file="$filename"
  if [ ! -f "$source_file" ]; then source_file="SOURCES/$filename"; fi
  cp "$source_file" "$topdir/SOURCES/"
done < <(sed -nE 's/^[^ ]+ \(([^)]+)\) = .*/\1/p' sources)
if [ -d SOURCES ]; then cp -a SOURCES/. "$topdir/SOURCES/"; fi
dnf builddep -y "$spec"
rpmbuild -ba "$spec" --define "_topdir $topdir" \
  --define "_sourcedir $topdir/SOURCES"
```

The explicit `--name` and `--namespace` preserve its CentOS lookaside identity even
when hosted in `okd-os`. On EL10, omit `epel-next-release`. Normal dependency,
build, and install checks remain separate from source planning.

## Workflow verification

With Python 3, PyYAML, Node.js, and Git installed, run
`python -m unittest discover -s .github/tests -v`. The tests execute the inline
workflow scripts against local repositories, exercising source selection,
upstream ancestry, patch replay, publication leases, and artifact collection.
They do not make Copilot requests or publish remote branches.

Actionlint 1.7.12 does not recognize the documented
[`copilot-requests` permission](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli-in-actions)
or [`queue: max`](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
When using that version, exclude only those diagnostics with
`-ignore 'unknown permission scope "copilot-requests"'` and
`-ignore 'unexpected key "queue" for "concurrency" section'`. Keep all other
workflow diagnostics enabled.
