# OKD 4.22 EL9 compose failure

Investigated on 2026-10-03 from [compose-base-image job 111310891061 in run
37158206826](https://github.com/Gentoli/okd-os/actions/runs/37158206826/job/111310891061).
The run used workflow commit `e4405efa4f3990e929f93be3273d668013929200`
on `rpm-mirror-run`. Its `openshift/os` checkout was
`cf63d7a58a420b35b7f5e42ea0e7deffec56cf91` from `release-4.22`.

## Observed failure

The EL9 fallback uses `scos-base:c9s` and invokes:

```text
rpm-ostree experimental compose treefile-apply --var osversion=centos-9 /run/src/packages-openshift.yaml
```

The compose fails with:

```text
Error: Unknown repo: 'ENOEXIST'
error: installing packages with dnf: Failed to run dnf install
```

RPM artifact collection and local repository generation had already succeeded;
`createrepo_c` reported 18 packages. The immediate failure occurs when applying
the OS package manifest.

## Cause

At the checked-out revision, upstream
[`packages-openshift.yaml`](https://github.com/openshift/os/blob/cf63d7a58a420b35b7f5e42ea0e7deffec56cf91/packages-openshift.yaml)
accepts only `rhel-9.8`, `rhel-10.2`, and `centos-10`. Its first conditional
selects the deliberately nonexistent repository `ENOEXIST` for other OS
versions. There is no `centos-9` conditional.

The upstream
[`build-node-image.sh`](https://github.com/openshift/os/blob/cf63d7a58a420b35b7f5e42ea0e7deffec56cf91/build-node-image.sh)
derives `osversion` from the base image's `ID` and `VERSION_ID`. The EL9 base
therefore selects `centos-9` and triggers that guard. The job also shows the
script loading upstream
[`c10s.repo`](https://github.com/openshift/os/blob/cf63d7a58a420b35b7f5e42ea0e7deffec56cf91/c10s.repo),
whose definitions target CentOS Stream 10.

The workflow's `repo_version: 9.8` supplies the local OpenShift repository
`rhel-9.8-server-ose-4.22`, which the script aliases to
`rhel-9.8-server-ose-4.22-okd`. That repository alias does not add CentOS 9
support to the manifest's OS conditionals.

## Required EL9 compose adaptation

Restore a `centos-9` conditional in the 4.22 manifest and provide matching
EL9 repository definitions. The 4.20
[`packages-openshift.yaml`](https://github.com/openshift/os/blob/847b7d8c3b60f60e86f1de0b7efebb746c75d1bc/packages-openshift.yaml)
and
[`c9s.repo`](https://github.com/openshift/os/blob/847b7d8c3b60f60e86f1de0b7efebb746c75d1bc/c9s.repo)
provide a reference for the CentOS 9 conditional and repository IDs.

Keep the 4.22 package requirements and postprocessing. Select EL9 BaseOS,
AppStream, and the appropriate NFV repository for Open vSwitch, together with
the local RPM repository containing the built 4.22 packages. The 4.20 Cloud SIG
repository in the reference should not be carried over as the source of the
4.22 runtime packages.

The adaptation must retain the actual `centos-9` base identity and select EL9
repositories. Removing the guard alone would leave the manifest without its
CentOS 9 repository selection.

## Local SIG package eligibility

The original run's local repository allowlist needed attention alongside the
manifest adaptation. In that run, the
[`compose workflow`](https://github.com/Gentoli/okd-os/blob/e4405efa4f3990e929f93be3273d668013929200/.github/workflows/build-okd-stream-coreos.yml)
extends the script's `includepkgs` with the unprefixed credential-provider RPM
names. The resulting allowlist admits OpenShift and provider packages but
excludes `cri-o`, `cri-tools`, and `conmon-rs`.

The compose workflow now adds `cri-o`, `cri-tools`, and `conmon-rs` package
patterns alongside the provider names. This eligibility change remains
unverified until the fallback compose selects packages from the local RPM
repository.

## Branch-based compatibility workflow

The release scan maintains the shared
[`sync-repo-mirror.yml`](../../.github/workflows/sync-repo-mirror.yml) workflow
once per OKD version: a `sync-os-source` matrix over the version's EL targets
checks `openshift/os:release-<version>` against
`Gentoli/okd-os:okd/os-<version>` and updates the mirror before any build leg
checks it out. Every EL target of a version shares one mirror branch, so the
scan derives a single entry per version and the build job waits for it. Only
fallback composition remains gated on release-image resolution, so builds that
use a matching release `stream-coreos` image still maintain the OS mirror. These
checks run through existing release-scan triggers; there is no independent
mirror schedule.

The OS mirror request injects OS-specific maintenance instructions into the
shared `.github/prompts/source-mirror-maintenance.md` prompt and uses the
general `.mirror-patch.json` identity marker. The injected instructions list the
version's EL targets, so for 4.22 the prompt rewinds `openshift/os` history to
the removed `centos-9` and `c9s.repo` definitions, restores them, then applies
the changes made since their removal — referencing the RHEL build definitions
when the branch still carries them — while preserving the current package set
and postprocessing and not reusing the older Cloud SIG runtime repository. For
4.22 it also fetches `release-4.20` as the reference for EL9 conditionals and
repository IDs. The compose workflow separately adds `cri-o`, `cri-tools`, and
`conmon-rs` to the local `includepkgs` allowlist while retaining the
credential-provider entries.

## Verification still needed

The shared workflow, caller wiring, and local allowlist are implemented in the
working copy. The first remote mirror bootstrap and full compose have not yet
run: CI must create `okd/os-4.22`, then verify that the intended EL9
repositories are selected, the built runtime and provider RPMs resolve, and
image composition and postprocessing complete. The CoreOS `coreos/c9s` branch
is also created by CI; keep its tracked fwupd patch available as the initial
bootstrap input until that branch and its first base build succeed.
