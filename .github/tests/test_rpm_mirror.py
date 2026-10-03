"""Execute the inline workflow scripts against local Git repositories.

Run with Python 3, PyYAML, Node.js, and Git:
    python -m unittest discover -s .github/tests -v
No GitHub credentials, Copilot requests, or remote writes are used.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
RUNNER = r"""
const fs = require('node:fs');
const child = require('node:child_process');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
Object.assign(process.env, input.env);
const outputs = {};
const customRequire = (name) => name === 'node:child_process' ? {
  ...child,
  execFileSync: (program, args, options) => {
    if (input.fail_remote && args.includes('ls-remote')) {
      throw Object.assign(new Error('network unavailable'), { status: 128 });
    }
    return child.execFileSync(program, args.map(a => input.urls[a] ?? a), options);
  },
} : require(name);
const core = { setOutput: (name, value) => { outputs[name] = value; },
  info: () => {}, setSecret: () => {} };
const github = input.releases ? { rest: { repos: {
  listReleases: async () => ({ data: input.releases }),
  getCommit: async ({ref}) => ({ data: { sha: ref + '-commit' } }),
} } } : {};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
(async () => {
  try {
    await new AsyncFunction('require', 'core', 'github', 'context', input.script)(customRequire, core, github, {});
    process.stdout.write(JSON.stringify({ outputs }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ error: error.message, outputs }));
  }
})();
"""


def workflow(name):
    # BaseLoader preserves the Actions "on" key instead of treating it as bool.
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def script(name, job, step):
    return next(s["with"]["script"] for s in workflow(name)["jobs"][job]["steps"] if s.get("id") == step)


class MirrorWorkflows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rpm-mirror-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        self.git("init", cwd=self.upstream)
        self.git("config", "user.name", "Test", cwd=self.upstream)
        self.git("config", "user.email", "test@example.com", cwd=self.upstream)
        self.git("config", "commit.gpgsign", "false", cwd=self.upstream)
        (self.upstream / "package.spec").write_text("upstream\n")
        self.commit(self.upstream, "upstream")
        self.base = self.git("rev-parse", "HEAD", cwd=self.upstream)
        self.git("branch", "c10s-sig-cloud-okd-4.22", cwd=self.upstream)
        self.git("branch", "c9s-sig-cloud", cwd=self.upstream)
        self.remote = self.root / "mirror.git"
        self.git("init", "--bare", str(self.remote))
        self.work = self.root / "workflow"
        self.git("clone", str(self.upstream), str(self.work))
        (self.work / "rpms").mkdir()
        self.rules = json.loads((ROOT / "rpms/mirror-plan.json").read_text())
        self.rules["sources"]["upstream_url_pattern"] = str(self.upstream)
        (self.work / "rpms/mirror-plan.json").write_text(json.dumps(self.rules))
        self.runner_temp = self.root / "runner"
        self.runner_temp.mkdir()
        # Each test repository has its own Git identity; ignore host signing,
        # credential helpers, and global URL rewrites.
        os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        self.env = {
            "GITHUB_REPOSITORY": "fixture/okd-os", "GITHUB_WORKSPACE": str(self.work),
            "RUNNER_TEMP": str(self.runner_temp), "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_TOKEN": "fixture-token",
            "PROJECT": "cri-o", "OKD_VERSION": "4.22", "OS_VERSION": "9",
        }
        self.urls = {"https://github.com/fixture/okd-os.git": str(self.remote)}

    def git(self, *args, cwd=None, check=True):
        result = subprocess.run(["git", *args], cwd=cwd or self.root,
                                capture_output=True, text=True, check=check)
        return result.stdout.strip() if check else result

    def commit(self, cwd, message):
        self.git("add", ".", cwd=cwd)
        self.git("-c", "commit.gpgsign=false", "commit", "-m", message, cwd=cwd)

    def run_script(self, source, **extra):
        result = subprocess.run(["node", "-e", RUNNER], cwd=self.work,
                                input=json.dumps({"script": source, "env": self.env, "urls": self.urls, **extra}),
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def select(self):
        return self.run_script(script("prepare-rpm-sources.yml", "select", "source"))

    def request(self):
        result = self.select()
        self.assertNotIn("error", result)
        return json.loads(result["outputs"]["mirror"])

    def prepare(self, request):
        self.env["MIRROR"] = json.dumps(request)
        result = self.run_script(script("sync-rpm-mirror.yml", "sync", "prepare"))
        self.assertNotIn("error", result)
        return result

    def seed_mirror(self, request):
        checkout = self.root / "existing"
        self.git("clone", str(self.upstream), str(checkout))
        self.git("config", "user.name", "Test", cwd=checkout)
        self.git("config", "user.email", "test@example.com", cwd=checkout)
        (checkout / ".rpm-patch.json").write_text(json.dumps({"id": request["patch_id"]}))
        self.commit(checkout, "PATCH/" + request["source_branch"])
        (checkout / "compatibility").write_text("target adaptation\n")
        self.commit(checkout, "Adapt target")
        self.git("push", str(self.remote), f"HEAD:refs/heads/{request['target_branch']}", cwd=checkout)
        return checkout

    def test_exact_upstream_takes_precedence(self):
        self.git("branch", "c9s-sig-cloud-okd-4.22", cwd=self.upstream)
        result = self.select()["outputs"]
        self.assertEqual(result["mirror"], "")
        source = json.loads(result["sources"])["4.22/el9"]["cri-o"]
        self.assertEqual(source["branch"], "c9s-sig-cloud-okd-4.22")

    def test_fallback_identity_is_branch_based(self):
        request = self.request()
        self.assertEqual(request["patch_id"], "cri-o__c10s-sig-cloud-okd-4.22__el9-okd4.22")
        self.assertEqual(request["target_branch"], "rpms/cri-o-el9-4.22")
        self.assertFalse(any("sha" in key for key in request))

    def test_shared_identity_is_independent_of_requested_release(self):
        self.env["PROJECT"] = "conmon-rs"
        first = self.request()
        self.env["OKD_VERSION"] = "4.20"
        self.assertEqual(first, self.request())
        self.assertIsNone(first["target_okd_version"])

    def test_missing_fallback_and_transport_failure_fail_selection(self):
        self.env["OKD_VERSION"] = "4.23"
        self.assertIn("Missing upstream", self.select()["error"])
        result = self.run_script(script("prepare-rpm-sources.yml", "select", "source"), fail_remote=True)
        self.assertIn("network unavailable", result["error"])
        self.assertEqual(result["outputs"], {})

    def test_missing_mirror_prepares_upstream_without_publishing(self):
        request = self.request()
        result = self.prepare(request)["outputs"]
        self.assertEqual(result["update"], "true")
        self.assertEqual(result["old_head"], "")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=result["worktree"]), self.base)
        self.assertEqual(self.git("show-ref", cwd=self.remote, check=False).returncode, 1)

    def test_current_mirror_skips_update_without_sha_metadata(self):
        request = self.request()
        self.seed_mirror(request)
        self.assertEqual(self.prepare(request)["outputs"], {"update": "false"})

    def test_advanced_upstream_replays_stack_and_lease_rejects_other_writer(self):
        request = self.request()
        existing = self.seed_mirror(request)
        old_head = self.git("rev-parse", "HEAD", cwd=existing)
        self.git("checkout", "c10s-sig-cloud-okd-4.22", cwd=self.upstream)
        (self.upstream / "upstream-new").write_text("new upstream content\n")
        self.commit(self.upstream, "Advance upstream")
        new_base = self.git("rev-parse", "HEAD", cwd=self.upstream)
        prepared = self.prepare(request)["outputs"]
        self.assertEqual(prepared["update"], "true")
        worktree = prepared["worktree"]
        self.git("checkout", "--detach", "refs/remotes/rpm-upstream/base", cwd=worktree)
        self.git("cherry-pick", f"{self.base}..{old_head}", cwd=worktree)
        self.assertEqual(self.git("merge-base", new_base, "HEAD", cwd=worktree), new_base)
        self.env.update({"WORKTREE": worktree, "OLD_HEAD": old_head,
                         "STAGING_BRANCH": prepared["staging_branch"],
                         "COMMITS": self.git("rev-list", "--reverse", f"{new_base}..HEAD", cwd=worktree).replace("\n", " ")})
        stage = self.run_script(script("sync-rpm-mirror.yml", "sync", "stage"))
        self.assertNotIn("error", stage)
        self.assertEqual(self.git("rev-parse", f"refs/heads/{prepared['staging_branch']}", cwd=self.remote), new_base)
        # A partially signed temporary branch must not affect the target mirror.
        self.assertEqual(self.git("rev-parse", f"refs/heads/{request['target_branch']}", cwd=self.remote), old_head)
        head = self.git("rev-parse", "HEAD", cwd=worktree)
        self.git("push", "rpm-mirror", f"HEAD:refs/heads/{prepared['staging_branch']}", cwd=worktree)
        self.env["SIGNED_HEAD"] = head  # Simulate the signer's output; no API call.
        publish_source = next(s["with"]["script"] for s in workflow("sync-rpm-mirror.yml")["jobs"]["sync"]["steps"] if s.get("name") == "Publish signed mirror with a lease")
        self.assertNotIn("error", self.run_script(publish_source))
        self.assertEqual(self.git("rev-parse", f"refs/heads/{request['target_branch']}", cwd=self.remote), head)
        # Another writer advances the mirror before a stale publisher retries.
        self.git("fetch", str(self.remote), f"refs/heads/{request['target_branch']}", cwd=existing)
        self.git("checkout", "--detach", "FETCH_HEAD", cwd=existing)
        (existing / "other-writer").write_text("concurrent update\n")
        self.commit(existing, "Another writer")
        other_head = self.git("rev-parse", "HEAD", cwd=existing)
        self.git("push", str(self.remote), f"HEAD:refs/heads/{request['target_branch']}", cwd=existing)
        self.assertIn("error", self.run_script(publish_source))
        self.assertEqual(self.git("rev-parse", f"refs/heads/{request['target_branch']}", cwd=self.remote), other_head)

    def test_artifact_fan_in_preserves_identical_filenames(self):
        source_dir = self.runner_temp / "rpm-sources"
        source_dir.mkdir()
        self.env["SOURCE_DIR"] = str(source_dir)
        for project in ("cri-o", "cri-tools", "conmon-rs"):
            artifact = source_dir / f"rpm-source-4.22-el9-{project}"
            artifact.mkdir()
            (artifact / "rpm-source.json").write_text(json.dumps({"4.22/el9": {project: {"url": "upstream", "branch": project}}}))
        action = yaml.load((ROOT / ".github/actions/collect-rpm-sources/action.yml").read_text(), Loader=yaml.BaseLoader)
        source = action["runs"]["steps"][1]["with"]["script"]
        result = self.run_script(source)["outputs"]
        self.assertEqual(set(json.loads(result["sources"])["4.22/el9"]), {"cri-o", "cri-tools", "conmon-rs"})

    def test_release_matrix_prepares_only_selected_targets_once(self):
        self.rules["build_targets"] = self.rules["build_targets"][:1]
        (self.work / "rpms/mirror-plan.json").write_text(json.dumps(self.rules))
        result = self.run_script(script("scan-okd-releases.yml", "release-matrix", "releases"), releases=[{
            "tag_name": "4.22.1-okd-scos.1", "body": "Pull From: quay.io/okd/scos-release@sha256:" + "a" * 64,
            "published_at": "2026-10-03", "draft": False, "prerelease": False,
        }])["outputs"]
        sources = json.loads(result["source_matrix"])
        self.assertEqual(len(sources), 3)
        self.assertEqual({row["os_version"] for row in sources}, {"9"})
        self.assertEqual(len({row["artifact_name"] for row in sources}), 3)

    def test_workflow_boundaries_and_failure_gates(self):
        for name in ("prepare-rpm-sources.yml", "sync-rpm-mirror.yml", "rpm-build.yml", "build-okd-stream-coreos.yml"):
            self.assertEqual(set(workflow(name)["on"]), {"workflow_call"})
        sync = workflow("sync-rpm-mirror.yml")
        self.assertEqual(len(sync["jobs"]), 1)
        self.assertIn("target_branch", sync["concurrency"]["group"])
        save = workflow("prepare-rpm-sources.yml")["jobs"]["save-source"]
        self.assertIn("needs.sync.result == 'success'", save["if"])
        builder = workflow("build-okd-stream-coreos.yml")["jobs"]["build-rpms"]
        self.assertNotIn("strategy", builder)
        self.assertNotIn("build_sig", (WORKFLOWS / "rpm-build.yml").read_text())


if __name__ == "__main__":
    unittest.main()
