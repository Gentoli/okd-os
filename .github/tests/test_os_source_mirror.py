"""Exercise the shared source-mirror workflow with local Git repositories."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from test_rpm_mirror import ROOT, RUNNER, script, workflow


class OsSourceMirror(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="os-source-mirror-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        self.git("init", "--initial-branch=main", cwd=self.upstream)
        self.git("config", "user.name", "Test", cwd=self.upstream)
        self.git("config", "user.email", "test@example.com", cwd=self.upstream)
        self.git("config", "commit.gpgsign", "false", cwd=self.upstream)
        (self.upstream / "packages-openshift.yaml").write_text("upstream manifest\n")
        (self.upstream / "c10s.repo").write_text("upstream repo definitions\n")
        self.commit(self.upstream, "Initial upstream source")
        self.base = self.git("rev-parse", "HEAD", cwd=self.upstream)
        self.git("branch", "release-4.20", cwd=self.upstream)
        self.git("branch", "release-4.22", cwd=self.upstream)

        self.upstream_remote = self.root / "upstream.git"
        self.git("init", "--bare", "--initial-branch=main", str(self.upstream_remote))
        self.git("push", str(self.upstream_remote), "--all", cwd=self.upstream)
        self.git("--git-dir", str(self.upstream_remote), "symbolic-ref", "HEAD", "refs/heads/main")

        self.remote = self.root / "mirror.git"
        self.git("init", "--bare", "--initial-branch=main", str(self.remote))
        self.work = self.root / "workflow"
        self.work.mkdir()
        self.git("init", "--initial-branch=main", cwd=self.work)
        self.git("config", "user.name", "Test", cwd=self.work)
        self.git("config", "user.email", "test@example.com", cwd=self.work)
        self.git("config", "commit.gpgsign", "false", cwd=self.work)
        (self.work / ".github/prompts").mkdir(parents=True)
        (self.work / ".github/prompts/source-mirror-maintenance.md").write_text(
            "Maintain the source mirror.\n"
        )
        (self.work / "docs").mkdir()
        (self.work / "docs/module-patch.md").write_text("RPM source recipe.\n")
        patch = self.work / "os/base/c9s/patches/0001-drop-unresolvable-fwupd-plugin.patch"
        patch.parent.mkdir(parents=True)
        patch.write_text("seed patch\n")
        self.commit(self.work, "Workflow checkout")

        self.runner_temp = self.root / "runner"
        self.runner_temp.mkdir()
        os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        self.env = {
            "GITHUB_REPOSITORY": "fixture/okd-os",
            "GITHUB_WORKSPACE": str(self.work),
            "RUNNER_TEMP": str(self.runner_temp),
            "GITHUB_RUN_ID": "456",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_TOKEN": "fixture-token",
        }
        self.urls = {
            "https://github.com/fixture/okd-os.git": str(self.remote),
            "https://github.com/coreos/rhel-coreos-config.git": str(self.upstream_remote),
            "https://github.com/openshift/os.git": str(self.upstream_remote),
        }

    def git(self, *args, cwd=None, check=True):
        result = subprocess.run(
            ["git", *args],
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            check=check,
        )
        return result.stdout.strip() if check else result

    def commit(self, cwd, message):
        self.git("add", ".", cwd=cwd)
        self.git("-c", "commit.gpgsign=false", "commit", "-m", message, cwd=cwd)

    def run_script(self, source, **extra):
        result = subprocess.run(
            ["node", "-e", RUNNER],
            cwd=self.work,
            input=json.dumps({
                "script": source,
                "env": self.env,
                "urls": self.urls,
                **extra,
            }),
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def request(self, project="coreos/rhel-coreos-config"):
        if project == "coreos/rhel-coreos-config":
            return {
                "project": project,
                "source_url": "https://github.com/coreos/rhel-coreos-config.git",
                "source_branch": "HEAD",
                "target_branch": "coreos/c9s",
                "target_version": None,
                "seed_patch": "os/base/c9s/patches/0001-drop-unresolvable-fwupd-plugin.patch",
            }
        return {
            "project": "openshift/os",
            "source_url": "https://github.com/openshift/os.git",
            "source_branch": "release-4.22",
            "target_branch": "okd/os-4.22",
            "target_version": "4.22",
            "reference_branch": "release-4.20",
        }

    def prepare(self, request):
        self.env["MIRROR"] = json.dumps(request)
        return self.run_script(script("sync-repo-mirror.yml", "sync", "prepare"))

    def seed_mirror(self, request):
        source_branch = "main" if request["source_branch"] == "HEAD" else request["source_branch"]
        checkout = self.root / "existing"
        self.git(
            "clone",
            "--single-branch",
            "--branch",
            source_branch,
            str(self.upstream_remote),
            str(checkout),
        )
        self.git("config", "user.name", "Test", cwd=checkout)
        self.git("config", "user.email", "test@example.com", cwd=checkout)
        marker = {
            "id": "fixture",
            "project": request["project"],
            "source_url": request["source_url"],
            "source_branch": source_branch,
            "target_branch": request["target_branch"],
            "target_version": request["target_version"],
        }
        (checkout / ".mirror-patch.json").write_text(json.dumps(marker) + "\n")
        self.commit(checkout, f"PATCH/{source_branch}")
        (checkout / "compatibility").write_text("target adaptation\n")
        self.commit(checkout, "Adapt target")
        self.git(
            "push",
            str(self.remote),
            f"HEAD:refs/heads/{request['target_branch']}",
            cwd=checkout,
        )
        return checkout

    def test_default_branch_resolution_and_coreos_bootstrap_context(self):
        result = self.prepare(self.request())
        self.assertNotIn("error", result)
        outputs = result["outputs"]
        self.assertEqual(outputs["update"], "true")
        self.assertEqual(outputs["old_head"], "")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=outputs["worktree"]), self.base)
        context = json.loads(
            (self.runner_temp / "source-mirror-context.json").read_text()
        )
        self.assertEqual(context["source_branch"], "main")
        self.assertEqual(context["target_branch"], "coreos/c9s")
        self.assertEqual(context["identity_file"], ".mirror-patch.json")
        self.assertEqual(
            context["prompt_file"], ".github/prompts/source-mirror-maintenance.md")
        self.assertEqual(
            context["seed_patch"],
            "os/base/c9s/patches/0001-drop-unresolvable-fwupd-plugin.patch",
        )
        self.assertIsNone(context["reference_ref"])

    def test_current_os_mirror_skips_agent_and_reference_fetch(self):
        request = self.request("openshift/os")
        self.seed_mirror(request)
        result = self.prepare(request)
        self.assertNotIn("error", result)
        self.assertEqual(result["outputs"], {"update": "false"})

    def test_os_request_fetches_el9_reference_for_422(self):
        result = self.prepare(self.request("openshift/os"))
        self.assertNotIn("error", result)
        context = json.loads(
            (self.runner_temp / "source-mirror-context.json").read_text()
        )
        self.assertEqual(context["source_branch"], "release-4.22")
        self.assertEqual(context["reference_ref"], "refs/remotes/mirror-upstream/reference")
        self.assertEqual(
            self.git("rev-parse", context["reference_ref"], cwd=self.work),
            self.git("rev-parse", "refs/heads/release-4.20", cwd=self.upstream),
        )

    def test_mirror_request_rejects_paths_outside_workflow_repository(self):
        request = self.request()
        request["prompt_file"] = "../outside.md"
        self.env["MIRROR"] = json.dumps(request)
        result = self.run_script(script("sync-repo-mirror.yml", "sync", "prepare"))
        self.assertIn("invalid prompt_file path", result["error"])
        self.assertEqual(result["outputs"], {})

    def test_generic_agent_reads_os_prompt_and_reports_commit_stack(self):
        self.env["RUNNER_TEMP"] = str(self.runner_temp)
        self.env["GITHUB_WORKSPACE"] = str(self.work)
        (self.runner_temp / "source-mirror-context.json").write_text(json.dumps({
            "prompt_file": ".github/prompts/source-mirror-maintenance.md",
            "recipe_file": "",
            "seed_patch": "",
        }))
        marker = "c3917c558a79c47db21bda758d655d7c04e6e792"
        patch = "3e5efb7689ed7f758b0f96f545046b20dbbc6655"
        result = self.run_script(
            script("sync-repo-mirror.yml", "sync", "agent"),
            agent_output=[f"COMMIT_OIDS: {marker} ", patch],
        )
        self.assertNotIn("error", result)
        self.assertEqual(result["outputs"]["commits"], f"{marker} {patch}")

    def test_publish_creates_branch_and_lease_rejects_concurrent_creation(self):
        request = self.request()
        prepared = self.prepare(request)["outputs"]
        worktree = Path(prepared["worktree"])
        self.git("checkout", "-b", "mirror-patch", cwd=worktree)
        marker = {
            "id": "fixture",
            "project": request["project"],
            "source_url": request["source_url"],
            "source_branch": "main",
            "target_branch": request["target_branch"],
            "target_version": None,
        }
        (worktree / ".mirror-patch.json").write_text(json.dumps(marker) + "\n")
        self.commit(worktree, "PATCH/main")
        marker_oid = self.git("rev-parse", "HEAD", cwd=worktree)
        (worktree / "compatibility").write_text("fwupd compatibility\n")
        self.commit(worktree, "Drop unresolved fwupd plugin")
        patch_oid = self.git("rev-parse", "HEAD", cwd=worktree)

        self.env.update({
            "WORKTREE": str(worktree),
            "COMMITS": f"{marker_oid} {patch_oid}",
            "STAGING_BRANCH": prepared["staging_branch"],
        })
        stage = self.run_script(script("sync-repo-mirror.yml", "sync", "stage"))
        self.assertNotIn("error", stage)
        self.assertEqual(
            self.git("--git-dir", str(self.remote), "rev-parse",
                     f"refs/heads/{prepared['staging_branch']}"),
            self.base,
        )

        self.git(
            "push",
            "mirror-target",
            f"{patch_oid}:refs/heads/{prepared['staging_branch']}",
            cwd=worktree,
        )
        self.env.update({
            "MIRROR": json.dumps(request),
            "OLD_HEAD": "",
            "SIGNED_HEAD": patch_oid,
        })
        publish = next(
            step["with"]["script"]
            for step in workflow("sync-repo-mirror.yml")["jobs"]["sync"]["steps"]
            if step.get("name") == "Publish signed mirror with a lease"
        )
        self.assertNotIn("error", self.run_script(publish))
        target_ref = f"refs/heads/{request['target_branch']}"
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", target_ref), patch_oid)

        concurrent = self.root / "concurrent"
        self.git(
            "clone",
            "--branch",
            request["target_branch"],
            str(self.remote),
            str(concurrent),
        )
        self.git("config", "user.name", "Other writer", cwd=concurrent)
        self.git("config", "user.email", "other@example.com", cwd=concurrent)
        (concurrent / "other-writer").write_text("concurrent branch creation\n")
        self.commit(concurrent, "Concurrent writer")
        concurrent_head = self.git("rev-parse", "HEAD", cwd=concurrent)
        self.git(
            "push",
            str(self.remote),
            f"HEAD:refs/heads/{request['target_branch']}",
            cwd=concurrent,
        )
        self.assertIn("error", self.run_script(publish))
        self.assertEqual(
            self.git("--git-dir", str(self.remote), "rev-parse", target_ref),
            concurrent_head,
        )

    def test_builders_use_the_shared_mirror_and_sync_every_version(self):
        base = workflow("build-scos-base.yml")
        base_jobs = base["jobs"]
        self.assertEqual(
            base_jobs["sync-coreos-source"]["uses"],
            "./.github/workflows/sync-repo-mirror.yml",
        )
        self.assertEqual(base_jobs["build-and-push"]["needs"], "sync-coreos-source")
        self.assertNotIn("inputs", base["on"]["workflow_dispatch"] or {})
        self.assertIn(
            "seed_patch",
            base_jobs["sync-coreos-source"]["with"]["repository_instructions"],
        )
        coreos_checkout = next(
            step for step in base_jobs["build-and-push"]["steps"]
            if step.get("name") == "Checkout CoreOS config"
        )
        self.assertEqual(coreos_checkout["with"]["ref"], "coreos/c9s")

        okd = workflow("build-okd-stream-coreos.yml")["jobs"]
        self.assertNotIn("sync-openshift-os-source", okd)
        self.assertEqual(
            okd["compose-base-image"]["needs"], ["resolve-source", "build-rpms"])
        os_checkout = next(
            step for step in okd["compose-base-image"]["steps"]
            if step.get("name") == "Checkout matching openshift/os source"
        )
        self.assertEqual(os_checkout["with"]["ref"], "okd/os-${{ inputs.version }}")

        scan = workflow("scan-okd-releases.yml")
        os_sync = scan["jobs"]["sync-os-source"]
        self.assertEqual(os_sync["uses"], "./.github/workflows/sync-repo-mirror.yml")
        self.assertEqual(
            os_sync["strategy"]["matrix"]["include"],
            "${{ fromJSON(needs.release-matrix.outputs.mirror_matrix) }}",
        )
        self.assertIn("sync-os-source", scan["jobs"]["build"]["needs"])
        instructions = os_sync["with"]["repository_instructions"]
        self.assertIn("Target EL versions: ${{ matrix.os_targets }}", instructions)
        self.assertIn("rhel", instructions)
        self.assertEqual(scan["on"]["schedule"][0]["cron"], "17 6 1,15 * *")
        self.assertEqual(scan["jobs"]["build"]["permissions"]["contents"], "write")
        self.assertEqual(scan["jobs"]["build"]["permissions"]["copilot-requests"], "write")
        self.assertIn(
            ".github/prompts/source-mirror-maintenance.md",
            scan["on"]["push"]["paths"],
        )
        self.assertFalse((ROOT / ".github/workflows/sync-os-source-mirror.yml").exists())

    def test_runtime_rpms_are_added_to_the_local_repository_allowlist(self):
        compose = workflow("build-okd-stream-coreos.yml")["jobs"]["compose-base-image"]
        step = next(
            step for step in compose["steps"]
            if step.get("name") == "Allow local runtime and provider RPM packages"
        )
        match = re.search(r"<<'PY'\n(.*?)\nPY", step["run"], re.DOTALL)
        self.assertIsNotNone(match)
        with tempfile.TemporaryDirectory(prefix="okd-includepkgs-test-") as temp:
            script_path = Path(temp) / "build-node-image.sh"
            script_path.write_text("includepkgs=ose-aws-ecr-*,ose-gcp-gcr-*\n")
            subprocess.run(
                [sys.executable, "-c", match.group(1), str(script_path), "4.22"],
                check=True,
                capture_output=True,
                text=True,
            )
            allowlist = script_path.read_text()
        for package_pattern in (
            "ecr-credential-provider*",
            "acr-credential-provider*",
            "gcr-credential-provider*",
            "crio-credential-provider*",
            "cri-o*",
            "cri-tools*",
            "conmon-rs*",
        ):
            self.assertIn(package_pattern, allowlist)


if __name__ == "__main__":
    unittest.main()
