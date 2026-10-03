# OKD CoreOS artifact smoke testing

Reviewed 2026-10-02. This smoke test targets the final OKD/SCOS node image,
not the separate SCOS base or the RPMs in isolation. The image workflow scans
stable OKD releases 4.20, 4.21, and 4.22 and builds c9s/c10s image variants.

## Recommended base-level test

The minimum useful smoke test is one ephemeral x86_64 Kola VM that pivots to the
exact image produced by the build, reboots into that deployment, and runs the
tests against the booted OKD image. It should not need a cluster or cloud
account.

1. Select the candidate by full GHCR pullspec. The workflow defaults to
   `ghcr.io/gentoli/stream-coreos:4.22-c9s`; manual runs can supply a tag or
   digest. Use a digest for a repeatable test of an exact build.
2. Pull the candidate from GHCR and the upstream comparison image from its
   registry with Skopeo, saving each as a local OCI archive. The workflow
   reads the release payload pullspec from the candidate's source labels and
   resolves its `stream-coreos` image with `oc adm release info`.
   No 4.20 tag is published in the separate public
   `quay.io/okd/centos-stream-coreos-9` repository.
3. Build a matching SCOS QEMU base with COSA. This is Kola's bootable
   starting disk; the final OCI image itself is not converted to an ISO. The
   base workflow uploads the QEMU disk as a run-specific artifact.
4. Give Kola each candidate archive with the `.ociarchive` suffix and
   `--oscontainer`. Kola copies it into the guest, runs
   `rpm-ostree rebase --experimental
   ostree-unverified-image:oci-archive:/var/tmp/<archive>`, and reboots. Tests
   then run against the guest booted from that candidate's installed OSTree
   deployment.
5. Mask Zincati in the initial VM's Ignition so its automatic update driver
   cannot block the test's manual rpm-ostree rebase. Kola supplies the test VM's
   Ignition and SSH access.
6. Run the `openshift`-tagged Kola suite for `--distro scos`, using the matching
   `openshift/os` release branch's external tests. Exclude the
   `rhaos-pkgs-match-openshift` test:
   its own description says it is RHCOS-only. The suite includes the
   Open vSwitch hugetlbfs group assertion, which declares SCOS support. Run the
   same tests independently against the upstream image and retain separate
   results so one failed pivot does not suppress the comparison.
7. Apply hard job and Kola timeouts. Upload Kola's serial console, journal, and
   test reports on success and failure.

The implemented
[`test-okd-stream-coreos.yml`](../../.github/workflows/test-okd-stream-coreos.yml)
workflow runs automatically after a successful main-branch image build and can
also be dispatched manually with full image pullspecs. Automatic runs use the
`4.22-c9s` GHCR tag and the payload recorded in its source labels; manual runs
can override the image and release payload. OKD images use
`<version>-<stream>` tags.

### Artifact and runner prerequisites

The current
[`build-scos-base.yml`](../../.github/workflows/build-scos-base.yml) workflow
builds and publishes the SCOS base OCI image and its QEMU boot disk from the
same COSA build. It publishes the OCI base as `<stream>` and the QEMU disk
container as `<stream>-vm`. The Kola workflow pulls that image and extracts the
QEMU disk. The
[`build-okd-stream-coreos.yml`](../../.github/workflows/build-okd-stream-coreos.yml)
workflow publishes the final node image to GHCR; the test pulls both candidate
images into local OCI archives rather than passing the image build's workflow
artifact.

Run the VM with QEMU/KVM on an x86_64 runner that exposes `/dev/kvm`. The
workflow checks for that device and fails rather than silently skipping the
boot test. The GHCR QEMU image remains available until its tag is removed. The
existing
[`rpm-build.yml` package-install check](../../.github/workflows/rpm-build.yml)
is useful coverage for RPM artifacts, but it does not boot the composed node
image.

### Historical 4.22 local Kola validation

On 2026-09-27, Kola pivoted the published image
(`sha256:c591da8f18a0247fdc856b8cbbfb4a4bfa85df8ab40635b4093be2ece85387a0`)
from a QEMU base built with the pinned c9s config. The Open vSwitch hugetlbfs
assertion and `rhcos.network.init-interfaces-test` passed after the reboot.
`crio.base` failed: CRI-O exited with `invalid plugin_dirs entry: mkdir
/opt/cni: file exists`, so the CRI socket was absent and kubelet could not
start. This result applies to the historical 4.22 image; the 4.20 candidate
needs its own Kola run before drawing a conclusion about CRI-O startup.

An initial trial using a Fedora CoreOS QEMU disk instead of the matching SCOS
base staged the pivot but failed OSTree staged-deployment finalization while
loading the SCOS SELinux policy. The test therefore uses a c9s QEMU base built
alongside the SCOS base rather than an unrelated generic CoreOS disk.

### Historical upstream comparison status

On 2026-09-27, the workflow's Skopeo copy-and-inspect path succeeded for both
`ghcr.io/gentoli/okd-stream-coreos:4.22` (amd64, version
`9.0.20260926-dev0`, digest
`sha256:c591da8f18a0247fdc856b8cbbfb4a4bfa85df8ab40635b4093be2ece85387a0`)
and `quay.io/okd/centos-stream-coreos-9:4.18-x86_64` (amd64, version
`418.9.202504300632-0`, digest
`sha256:b7af2e6cd46cfffee7c729a3d44f701c000661ef5a467a4620803eb0db1dc98a`).
The Kola comparison has not been run in this session because no SCOS QEMU disk
artifact was available locally; the run-specific artifact will be produced by
the updated SCOS base workflow. Therefore, whether the upstream image
reproduces `invalid plugin_dirs entry: mkdir /opt/cni: file exists` remains
unverified. The workflow is configured to run that comparison and upload its
results independently.

## Existing upstream Kola tests

The pinned [`openshift/os` 4.20 Kola test tree](https://github.com/openshift/os/tree/847b7d8c3b60f60e86f1de0b7efebb746c75d1bc/tests/kola)
contains two image-oriented tests:

- [`openvswitch-hugetlbfs-groups`](https://github.com/openshift/os/blob/847b7d8c3b60f60e86f1de0b7efebb746c75d1bc/tests/kola/files/openvswitch-hugetlbfs-groups)
  checks that the `openvswitch` user belongs to the `hugetlbfs` group. It
  declares support for x86_64 and ppc64le; the current OKD image workflow
  produces x86_64.
- [`rhaos-pkgs-match-openshift`](https://github.com/openshift/os/blob/847b7d8c3b60f60e86f1de0b7efebb746c75d1bc/tests/kola/version/rhaos-pkgs-match-openshift)
  checks that RHAOS RPMs match `OPENSHIFT_VERSION`. The script says it is RHCOS
  only and excludes packages with known version exceptions, so it should not be
  copied unchanged for SCOS. Adapt the assertion only after confirming which
  package version metadata is meaningful for the OKD artifact.

The smoke workflow uses the hugetlbfs group check when running
`--tag openshift`; the RHAOS package-version check is explicitly denylisted
because it targets RHCOS. Kola supplies the VM setup, archive pivot, reboot,
and artifact handoff that the assertions alone do not cover.

## Additional OpenShift CI coverage

The [`openshift/os` 4.20 ci-operator config](https://github.com/openshift/release/blob/main/ci-operator/config/openshift/os/openshift-os-release-4.20.yaml)
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
