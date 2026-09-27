# OKD CoreOS artifact smoke testing

Reviewed 2026-09-27. This smoke test targets the final OKD/SCOS node image
composed from the pinned `openshift/os` source, not the separate SCOS base or
the RPMs in isolation.

## Recommended base-level test

The minimum useful smoke test is one ephemeral x86_64 Kola VM that pivots to the
exact image produced by the build, reboots into that deployment, and runs the
tests against the booted OKD image. It should not need a cluster or cloud
account.

1. Pass the exact build output to the test job using the image workflow run ID.
   The test downloads that run's OCI archive, not a mutable registry tag.
2. Build a matching SCOS `c9s` QEMU base with COSA. This is Kola's bootable
   starting disk; the final OCI image itself is not converted to an ISO.
3. Give Kola the candidate archive with the `.ociarchive` suffix and
   `--oscontainer`. Kola copies it into the guest, runs
   `rpm-ostree rebase --experimental
   ostree-unverified-image:oci-archive:/var/tmp/<archive>`, and reboots. Tests
   then run against the guest booted from the candidate's installed OSTree
   deployment.
4. Mask Zincati in the initial VM's Ignition so its automatic update driver
   cannot block the test's manual rpm-ostree rebase. Kola supplies the test VM's
   Ignition and SSH access.
5. Run the `openshift`-tagged Kola suite for `--distro scos`, using the pinned
   `openshift/os` external tests. Exclude the `rhaos-pkgs-match-openshift` test:
   its own description says it is RHCOS-only. The suite includes the
   Open vSwitch hugetlbfs group assertion, which declares SCOS support.
6. Apply hard job and Kola timeouts. Upload Kola's serial console, journal, and
   test reports on success and failure.

The implemented
[`test-okd-stream-coreos.yml`](../../.github/workflows/test-okd-stream-coreos.yml)
workflow runs automatically after a successful main-branch image build and can
also be dispatched manually with an image workflow run ID. The QEMU base uses
the CoreOS config revision that produced the currently pinned base image; update
that revision when changing the base-image digest in the image workflow.

### Artifact and runner prerequisites

The current
[`build-okd-stream-coreos.yml`](../../.github/workflows/build-okd-stream-coreos.yml)
composes and publishes the final image, then uploads an OCI archive as a
run-specific workflow artifact. The Kola workflow renames that artifact to
`.ociarchive` because that suffix activates Kola's local-archive pivot path. A
separate COSA `c9s` QEMU build is required to boot the test VM; it must use a
compatible SCOS base, including its SELinux policy.

Run the VM with QEMU/KVM on an x86_64 runner that exposes `/dev/kvm`. The
workflow checks for that device and fails rather than silently skipping the
boot test. The image artifact is retained for 14 days, which also limits the
manual-dispatch window. The existing
[`rpm-build.yml` package-install check](../../.github/workflows/rpm-build.yml)
is useful coverage for RPM artifacts, but it does not boot the composed node
image.

## Existing upstream Kola tests

The current [`openshift/os` Kola test tree](https://github.com/openshift/os/tree/master/tests/kola)
contains two image-oriented tests:

- [`openvswitch-hugetlbfs-groups`](https://github.com/openshift/os/blob/master/tests/kola/files/openvswitch-hugetlbfs-groups)
  checks that the `openvswitch` user belongs to the `hugetlbfs` group. It
  declares support for x86_64 and ppc64le; the current OKD image workflow
  produces x86_64.
- [`rhaos-pkgs-match-openshift`](https://github.com/openshift/os/blob/master/tests/kola/version/rhaos-pkgs-match-openshift)
  checks that RHAOS RPMs match `OPENSHIFT_VERSION`. The script says it is RHCOS
  only and excludes packages with known version exceptions, so it should not be
  copied unchanged for SCOS. Adapt the assertion only after confirming which
  package version metadata is meaningful for the OKD artifact.

The smoke workflow uses the hugetlbfs group check when running
`--tag openshift`; the RHAOS package-version check is explicitly denylisted
because it targets RHCOS. Kola supplies the VM setup, archive pivot, reboot,
and artifact handoff that the assertions alone do not cover.

## Additional OpenShift CI coverage

The [`openshift/os` 4.22 ci-operator config](https://github.com/openshift/release/blob/main/ci-operator/config/openshift/os/openshift-os-release-4.22.yaml)
defines an optional `e2e-aws` test using the `openshift-e2e-aws` workflow. Its
`latest` release includes built images, so this is broader cluster-level
coverage of the candidate image, rather than a focused single-node smoke test.
The [`master` OKD SCOS config](https://github.com/openshift/release/blob/main/ci-operator/config/openshift/os/openshift-os-master__okd-scos.yaml)
also defines an optional AWS E2E job (`e2e-aws-ovn`). OpenShift's generated
[Prow presubmits](https://github.com/openshift/release/blob/main/ci-operator/jobs/openshift/os/openshift-os-master-presubmits.yaml)
include image/release builds and optional E2E jobs. These jobs need OpenShift
CI infrastructure; the AWS E2E specifically also needs its AWS cluster profile.
They are not a baseline GitHub Actions test and do not replace the proposed
local VM boot check.

## Suggested follow-on coverage

After the single-VM smoke test is reliable, consider a small cluster install
test, upgrades/reboots across deployments, and additional architectures. Keep
those separate from the base gate: they cost more, take longer, and require
infrastructure or coverage not available in the current x86_64 image workflow.
