# OKD CoreOS artifact smoke testing

Reviewed 2026-09-27. This plan targets the final OKD/SCOS node image composed
from the pinned `openshift/os` source, not the separate SCOS base or the RPMs
in isolation.

## Recommended base-level test

The minimum useful smoke test is one ephemeral x86_64 VM that installs and boots
the exact image produced by the build, then reboots from its installed disk.
It should not need a cluster or cloud account.

1. Pass the exact build output to the test job, identified by its workflow run
   and source/RPM inputs; do not resolve a mutable registry tag during testing.
2. Use a supported CoreOS installation/deployment path to put that image on a
   fresh VM disk. Remove the installer/live media and boot the installed disk.
   A live-ISO boot or running the OCI image with Podman does not satisfy this
   test.
3. Wait for the guest to finish booting and become reachable through a
   test-only Ignition/SSH key. Apply a hard timeout and retain the serial
   console output if boot or access fails.
4. In the guest, verify the expected OS identity and architecture, that the
   booted OSTree deployment corresponds to the tested build, and that the
   OpenShift node packages selected by the pinned manifest are present. At
   minimum, check `cri-o`, `cri-tools`, `conmon-rs`, `openshift-clients`,
   `openshift-kubelet`, `openvswitch3.5`, the manifest's credential-provider
   packages, and their expected executables. Check that systemd is responsive;
   only require services to be active when they are expected to run before
   cluster bootstrap.
5. Reboot the guest from its installed disk, reconnect, and repeat the
   deployment and package checks. Fail on install/boot/reboot timeout, an
   unexpected deployment, missing required content, or inability to reach the
   guest.
6. Upload serial output and guest diagnostics (journal, OSTree status, OS
   release, and package inventory) on success and failure.

### Artifact and runner prerequisites

The current
[`build-okd-stream-coreos.yml`](../../.github/workflows/build-okd-stream-coreos.yml)
composes and publishes the final image, then uploads an OCI archive as a
workflow artifact. That archive is not a raw, QCOW2, or ISO VM disk. Before
adding the smoke job, establish the supported way to install/deploy that exact
composed image onto a VM disk. If the OCI output has no supported direct path,
the build must also produce a bootable test artifact from the same source and
package inputs; testing only the SCOS base would miss regressions in the OKD
compose.

Run the VM with QEMU/KVM on an x86_64 runner that exposes `/dev/kvm`. This
repository's [`build-scos-base.yml`](../../.github/workflows/build-scos-base.yml)
already checks for that device before running COSA. Make the smoke job perform
the same preflight and fail clearly rather than silently skipping the boot
test. Keep it in the same workflow run as the image build, and pass the
immutable artifact or digest rather than downloading a later tag. The existing
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

The hugetlbfs group check is a reasonable candidate for the base smoke suite if
the built image includes Open vSwitch. These tests provide useful assertions,
but do not by themselves specify the VM installation, reboot, and artifact
handoff needed for this GitHub Actions test.

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
