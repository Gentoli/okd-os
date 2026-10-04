"""Execute the inline workflow scripts against local Git repositories.

Run with Python 3, PyYAML, Node.js, and Git:
    python -m unittest discover -s .github/tests -v
No GitHub credentials, Copilot requests, or remote writes are used.
"""

from fnmatch import fnmatchcase
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
const spawns = [];
const customRequire = (name) => name === 'node:child_process' ? {
  ...child,
  execFileSync: (program, args, options) => {
    if (input.fail_remote && args.includes('ls-remote')) {
      throw Object.assign(new Error('network unavailable'), { status: 128 });
    }
    return child.execFileSync(program, args.map(a => input.urls[a] ?? a), options);
  },
  spawn: (program, args) => {
    if (input.agent_output === undefined) throw new Error('Copilot requests are disabled in tests');
    spawns.push([program, ...args]);
    const { EventEmitter } = require('node:events');
    const agent = new EventEmitter();
    agent.stdout = new EventEmitter();
    process.nextTick(() => {
      for (const chunk of input.agent_output) agent.stdout.emit('data', Buffer.from(chunk));
      agent.emit('close', 0);
    });
    return agent;
  },
} : require(name);
const core = { setOutput: (name, value) => { outputs[name] = value; },
  info: () => {}, setSecret: () => {}, warning: () => {} };
const github = input.releases ? { rest: { repos: {
  listReleases: async () => ({ data: input.releases }),
  getCommit: async ({ref}) => ({ data: { sha: ref + '-commit' } }),
} } } : {};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const workflowProcess = input.agent_output === undefined ? process : {
  env: process.env, stdout: { write: () => {} },
};
(async () => {
  try {
    await new AsyncFunction('require', 'core', 'github', 'context', 'process', input.script)(customRequire, core, github, {}, workflowProcess);
    process.stdout.write(JSON.stringify({ outputs, spawns }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ error: error.message, outputs, spawns }));
  }
})();
"""


def workflow(name):
    # BaseLoader preserves the Actions "on" key instead of treating it as bool.
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def script(name, job, step):
    return next(s["with"]["script"] for s in workflow(name)["jobs"][job]["steps"] if s.get("id") == step)


def action_script(name, step):
    action = yaml.load((ROOT / ".github/actions" / name / "action.yml").read_text(), Loader=yaml.BaseLoader)
    return next(s["with"]["script"] for s in action["runs"]["steps"] if s.get("id") == step)


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
        result = self.run_script(script("sync-repo-mirror.yml", "sync", "prepare"))
        self.assertNotIn("error", result)
        return result

    def seed_mirror(self, request):
        checkout = self.root / "existing"
        self.git("clone", str(self.upstream), str(checkout))
        self.git("config", "user.name", "Test", cwd=checkout)
        self.git("config", "user.email", "test@example.com", cwd=checkout)
        (checkout / ".mirror-patch.json").write_text(json.dumps({"id": request["patch_id"]}))
        self.commit(checkout, "PATCH/" + request["source_branch"])
        (checkout / "compatibility").write_text("target adaptation\n")
        self.commit(checkout, "Adapt target")
        # Published stacks carry their size so a truncated mirror stays detectable.
        self.git("commit", "--amend", "--no-edit",
                 "--trailer", "Mirror-Stack: 2", cwd=checkout)
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
        self.assertNotIn("identity_file", request)
        self.assertNotIn("prompt_file", request)
        self.assertEqual(request["recipe_file"], "docs/module-patch.md")
        self.assertFalse(any("sha" in key for key in request))
        self.assertIn(
            "SPECS",
            workflow("prepare-rpm-sources.yml")["jobs"]["sync"]["with"]["repository_instructions"],
        )

    def test_native_shared_el9_source_is_direct_for_both_releases(self):
        self.env["PROJECT"] = "conmon-rs"
        for version in ("4.22", "4.20"):
            with self.subTest(version=version):
                self.env["OKD_VERSION"] = version
                result = self.select()
                self.assertNotIn("error", result)
                self.assertEqual(result["outputs"]["mirror"], "")
                source = json.loads(result["outputs"]["sources"])[f"{version}/el9"]["conmon-rs"]
                self.assertEqual(source, {"url": str(self.upstream), "branch": "c9s-sig-cloud"})

    def test_native_shared_el10_source_is_direct_when_exact_is_absent(self):
        self.git("branch", "c10s-sig-cloud", cwd=self.upstream)
        self.env.update({"PROJECT": "conmon-rs", "OS_VERSION": "10"})
        result = self.select()["outputs"]
        self.assertEqual(result["mirror"], "")
        self.assertEqual(json.loads(result["sources"])["4.22/el10"]["conmon-rs"],
                         {"url": str(self.upstream), "branch": "c10s-sig-cloud"})

    def test_exact_conmon_source_precedes_native_shared_branch(self):
        self.git("branch", "c10s-sig-cloud", cwd=self.upstream)
        self.git("branch", "cloud10s-okd-4.22-el10s", cwd=self.upstream)
        self.env.update({"PROJECT": "conmon-rs", "OS_VERSION": "10"})
        result = self.select()["outputs"]
        self.assertEqual(result["mirror"], "")
        self.assertEqual(json.loads(result["sources"])["4.22/el10"]["conmon-rs"]["branch"],
                         "cloud10s-okd-4.22-el10s")

    def test_missing_or_unreachable_shared_source_fails_without_mirror_request(self):
        self.env["PROJECT"] = "conmon-rs"
        self.git("branch", "-D", "c9s-sig-cloud", cwd=self.upstream)
        result = self.select()
        self.assertIn("Missing upstream source branch: c9s-sig-cloud", result["error"])
        self.assertEqual(result["outputs"], {})
        result = self.run_script(script("prepare-rpm-sources.yml", "select", "source"), fail_remote=True)
        self.assertIn("network unavailable", result["error"])
        self.assertEqual(result["outputs"], {})

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
        self.assertEqual(
            self.git("--git-dir", str(self.remote), "show-ref", check=False).returncode,
            1,
        )

    def test_current_mirror_skips_update_without_sha_metadata(self):
        request = self.request()
        self.seed_mirror(request)
        self.assertEqual(self.prepare(request)["outputs"], {"update": "false"})

    def test_truncated_mirror_without_stack_trailer_reruns_maintenance(self):
        request = self.request()
        checkout = self.seed_mirror(request)
        # A partially published stack loses the trailer-bearing head commit.
        marker = self.git("rev-parse", "HEAD^", cwd=checkout)
        self.git("push", "--force", str(self.remote),
                 f"{marker}:refs/heads/{request['target_branch']}", cwd=checkout)
        self.assertEqual(self.prepare(request)["outputs"]["update"], "true")

    def agent_report(self, output):
        self.env.update({"GITHUB_WORKSPACE": str(ROOT), "WORKTREE": str(self.work)})
        (self.runner_temp / "source-mirror-context.json").write_text(json.dumps({
            "prompt_file": ".github/prompts/source-mirror-maintenance.md",
            "recipe_file": "docs/module-patch.md",
        }))
        # Split the report as streamed CLI output, without making an agent request.
        return self.run_script(script("sync-repo-mirror.yml", "sync", "agent"),
                               agent_output=[output[:20], output[20:]])

    def test_agent_injects_repository_instructions_into_the_prompt(self):
        self.env["REPOSITORY_INSTRUCTIONS"] = "Inspect the packaging lookaside manifest."
        result = self.agent_report(
            "COMMIT_OIDS: c3917c558a79c47db21bda758d655d7c04e6e792")
        self.assertNotIn("error", result)
        prompt = result["spawns"][0][2]
        self.assertIn("# Maintain one source mirror", prompt)
        injected = prompt.index("\n\nRepository instructions:\n")
        self.assertLess(
            injected, prompt.index("Inspect the packaging lookaside manifest."))
        self.assertLess(prompt.index("Inspect the packaging lookaside manifest."), prompt.index("Recipe:"))
        self.assertLess(prompt.index("Recipe:"), prompt.index("Run context:"))

    def test_agent_reports_preserve_order_with_literal_optional_brackets(self):
        marker = "c3917c558a79c47db21bda758d655d7c04e6e792"
        patch = "3e5efb7689ed7f758b0f96f545046b20dbbc6655"
        for report in (marker, f"{marker} {patch}", f"{marker} [{patch}]",
                       f"[{marker} {patch}]"):
            with self.subTest(report=report):
                result = self.agent_report(f"Created mirror commits.\n\nCOMMIT_OIDS: {report}\r\n")
                self.assertNotIn("error", result)
                self.assertEqual(result["outputs"]["commits"], report.replace("[", "").replace("]", ""))

    def test_agent_rejects_incomplete_or_missing_commit_reports(self):
        marker = "c3917c558a79c47db21bda758d655d7c04e6e792"
        for report in ("No report", "COMMIT_OIDS: NONE", "COMMIT_OIDS: abc123",
                       f"COMMIT_OIDS: {marker} [abc123]", f"COMMIT_OIDS: {marker} [",
                       f"COMMIT_OIDS: {marker} explanation"):
            with self.subTest(report=report):
                result = self.agent_report(report + "\n")
                self.assertIn("error", result)
        self.assertEqual(result["outputs"], {})

    def test_agent_reads_the_stack_from_the_required_branch(self):
        self.env.update({"GITHUB_WORKSPACE": str(ROOT), "WORKTREE": str(self.work)})
        self.git("config", "user.name", "Test", cwd=self.work)
        self.git("config", "user.email", "test@example.com", cwd=self.work)
        base = self.git("rev-parse", "HEAD", cwd=self.work)
        (self.work / "marker").write_text("identity\n")
        self.commit(self.work, "PATCH/c10s-sig-cloud-okd-4.22")
        marker = self.git("rev-parse", "HEAD", cwd=self.work)
        (self.work / "adaptation").write_text("target adaptation\n")
        self.commit(self.work, "Adapt the target")
        head = self.git("rev-parse", "HEAD", cwd=self.work)
        self.git("branch", "--force", "mirror-patch", "HEAD", cwd=self.work)
        (self.runner_temp / "source-mirror-context.json").write_text(json.dumps({
            "prompt_file": ".github/prompts/source-mirror-maintenance.md",
            "recipe_file": "",
            "source_ref": base,
            "stack_branch": "mirror-patch",
            "source_branch": "c10s-sig-cloud-okd-4.22",
        }))
        # The transcript is irrelevant; Git supplies the ordered stack.
        result = self.run_script(script("sync-repo-mirror.yml", "sync", "agent"),
                                 agent_output=["Finished without reporting commit IDs.\n"])
        self.assertNotIn("error", result)
        self.assertEqual(result["outputs"]["commits"], f"{marker} {head}")

    def test_agent_requires_the_stack_branch(self):
        self.env.update({"GITHUB_WORKSPACE": str(ROOT), "WORKTREE": str(self.work)})
        (self.runner_temp / "source-mirror-context.json").write_text(json.dumps({
            "prompt_file": ".github/prompts/source-mirror-maintenance.md",
            "recipe_file": "",
            "source_ref": self.base,
            "stack_branch": "mirror-patch",
            "source_branch": "c10s-sig-cloud-okd-4.22",
        }))
        result = self.run_script(script("sync-repo-mirror.yml", "sync", "agent"),
                                 agent_output=["Finished without reporting commit IDs.\n"])
        self.assertIn("mirror-patch branch", result["error"])

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
        self.git("checkout", "--detach", "refs/remotes/mirror-upstream/base", cwd=worktree)
        self.git("cherry-pick", f"{self.base}..{old_head}", cwd=worktree)
        self.assertEqual(self.git("merge-base", new_base, "HEAD", cwd=worktree), new_base)
        self.env.update({
            "WORKTREE": worktree,
            "OLD_HEAD": old_head,
            "BASE": new_base,
            "UNSIGNED_HEAD": self.git("rev-parse", "HEAD", cwd=worktree),
            "STAGING_BRANCH": prepared["staging_branch"],
            "COMMITS": self.git("rev-list", "--reverse", f"{new_base}..HEAD", cwd=worktree).replace("\n", " "),
        })
        stage = self.run_script(script("sync-repo-mirror.yml", "sync", "stage"))
        self.assertNotIn("error", stage)
        self.assertEqual(
            self.git("--git-dir", str(self.remote), "rev-parse",
                     f"refs/heads/{prepared['staging_branch']}"),
            new_base,
        )
        # A partially signed temporary branch must not affect the target mirror.
        self.assertEqual(
            self.git("--git-dir", str(self.remote), "rev-parse",
                     f"refs/heads/{request['target_branch']}"),
            old_head,
        )
        head = self.git("rev-parse", "HEAD", cwd=worktree)
        self.git("push", "mirror-target", f"HEAD:refs/heads/{prepared['staging_branch']}", cwd=worktree)
        self.env["SIGNED_HEAD"] = head  # Simulate the signer's output; no API call.
        publish_source = next(s["with"]["script"] for s in workflow("sync-repo-mirror.yml")["jobs"]["sync"]["steps"] if s.get("name") == "Publish mirror with a lease")
        self.assertNotIn("error", self.run_script(publish_source))
        self.assertEqual(
            self.git("--git-dir", str(self.remote), "rev-parse",
                     f"refs/heads/{request['target_branch']}"),
            head,
        )
        self.assertEqual(
            self.git("--git-dir", str(self.remote), "log", "-1",
                     "--format=%(trailers:key=Mirror-Stack,valueonly)",
                     f"refs/heads/{request['target_branch']}"),
            "2",
        )
        # Another writer advances the mirror before a stale publisher retries.
        self.git("fetch", str(self.remote), f"refs/heads/{request['target_branch']}", cwd=existing)
        self.git("checkout", "--detach", "FETCH_HEAD", cwd=existing)
        (existing / "other-writer").write_text("concurrent update\n")
        self.commit(existing, "Another writer")
        other_head = self.git("rev-parse", "HEAD", cwd=existing)
        self.git("push", str(self.remote), f"HEAD:refs/heads/{request['target_branch']}", cwd=existing)
        self.assertIn("error", self.run_script(publish_source))
        self.assertEqual(
            self.git("--git-dir", str(self.remote), "rev-parse",
                     f"refs/heads/{request['target_branch']}"),
            other_head,
        )

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
        mirror = json.loads(result["mirror_matrix"])
        self.assertEqual(mirror, [{"version": "4.22", "os_targets": "9"}])

    def test_release_matrix_syncs_each_version_once(self):
        releases = [{
            "tag_name": f"{version}.1-okd-scos.1",
            "body": "Pull From: quay.io/okd/scos-release@sha256:" + "b" * 64,
            "published_at": "2026-10-03", "draft": False, "prerelease": False,
        } for version in ("4.22", "4.20")]
        result = self.run_script(
            script("scan-okd-releases.yml", "release-matrix", "releases"),
            releases=releases)["outputs"]
        # 4.22 builds EL9 and EL10 from one mirror branch, so the scan syncs it
        # once and every build leg waits for that single sync.
        self.assertEqual(json.loads(result["mirror_matrix"]), [
            {"version": "4.22", "os_targets": "9, 10"},
            {"version": "4.20", "os_targets": "9"},
        ])

    def test_parallel_rpm_matrices_preserve_sources_and_collectible_artifacts(self):
        supplied = {
            "cri-o": {"url": "https://mirror.example/cri-o.git", "branch": "rpms/cri-o-el9-4.22"},
            "cri-tools": {"url": "https://upstream.example/cri-tools.git", "branch": "c10s-sig-cloud-okd-4.22"},
            "conmon-rs": {"url": "https://upstream.example/conmon-rs.git", "branch": "c9s-sig-cloud"},
        }
        targets = [{"version": version, "os_major": el, "run_test": False, "release_image": "selected-image"}
                   for version, el in (("4.22", "9"), ("4.22", "10"), ("4.21", "9"), ("4.20", "9"))]
        self.env["TARGETS"] = json.dumps(targets)
        self.env["SOURCES"] = json.dumps({f"{target['version']}/el{target['os_major']}": supplied
                                        for target in targets})
        result = self.run_script(action_script("prepare-rpm-build-matrices", "configs"))
        self.assertNotIn("error", result)
        configs = json.loads(result["outputs"]["matrix"])
        self.assertEqual(len(configs), len(targets))
        all_artifacts = []
        for target, config in zip(targets, configs):
            version, el = target["version"], target["os_major"]
            with self.subTest(version=version, el=el):
                self.assertEqual({key: config[key] for key in target}, target)
                upstream = json.loads(config["upstream_matrix"])
                sig = json.loads(config["sig_matrix"])
                components = {row["component"] for row in upstream}
                self.assertEqual(len(upstream), 6 if version in ("4.21", "4.22") else 5)
                self.assertEqual("crio-credential-provider" in components, version in ("4.21", "4.22"))
                self.assertTrue({"kubernetes", "oc", "ecr-credential-provider",
                                 "acr-credential-provider", "gcr-credential-provider"} <= components)
                self.assertEqual({row["project"]: {"url": row["source_url"], "branch": row["source_branch"]}
                                  for row in sig}, supplied)
                names = [row["artifact_name"] for row in upstream + sig]
                self.assertTrue(all(fnmatchcase(name, f"*-rpms-okd{version}-el{el}") for name in names))
                all_artifacts.extend(names)
        self.assertEqual(len(set(all_artifacts)), len(all_artifacts))

    def test_parallel_rpm_builds_expand_inputs_and_install_waits_for_all(self):
        jobs = workflow("rpm-build.yml")["jobs"]
        self.assertNotIn("build-matrix", jobs)
        for name, matrix_input in (("build-rpms", "upstream_matrix"), ("build-rpms-centos-sig", "sig_matrix")):
            build = jobs[name]
            self.assertNotIn("needs", build)
            self.assertEqual(build["strategy"]["matrix"]["include"], "${{ fromJSON(inputs." + matrix_input + ") }}")
            self.assertEqual(build["strategy"]["fail-fast"], "false")
            upload = next(step for step in build["steps"] if step.get("uses") == "actions/upload-artifact@v4")
            self.assertEqual(upload["with"]["name"], "${{ matrix.artifact_name }}")
            self.assertEqual(upload["with"]["if-no-files-found"], "error")
        install = jobs["test-rpm-install"]
        self.assertEqual(set(install["needs"]), {"build-rpms", "build-rpms-centos-sig"})
        self.assertEqual(install["if"], "inputs.run_test")
        self.assertEqual(install["steps"][0]["with"]["merge-multiple"], "true")

    def test_missing_prepared_sources_fail_before_build_configurations(self):
        self.env["TARGETS"] = json.dumps([{"version": "4.22", "os_major": "9"}])
        self.env["SOURCES"] = json.dumps({"4.22/el9": {"cri-o": {"url": "mirror", "branch": "prepared"}}})
        result = self.run_script(action_script("prepare-rpm-build-matrices", "configs"))
        self.assertIn("Missing prepared RPM sources for 4.22/el9", result["error"])
        self.assertEqual(result["outputs"], {})

    def test_scan_and_reproduction_share_matrix_generation_and_pass_it_to_builds(self):
        shared = "./.github/actions/prepare-rpm-build-matrices"
        scan = workflow("scan-okd-releases.yml")["jobs"]
        manual = workflow("reproduce-rpm-build.yml")["jobs"]
        for job in (scan["compose-build-configs"], manual["collect-rpm-sources"]):
            step = next(s for s in job["steps"] if s.get("id") == "configs")
            self.assertEqual(step["uses"], shared)
            self.assertEqual(step["with"]["sources"], "${{ steps.sources.outputs.sources }}")
        result = self.run_script(script("reproduce-rpm-build.yml", "source-matrix", "matrix"))
        self.assertEqual(json.loads(result["outputs"]["targets"]), [{"version": "4.22", "os_major": "9"}])
        image = workflow("build-okd-stream-coreos.yml")["jobs"]["build-rpms"]
        for matrix_input in ("upstream_matrix", "sig_matrix"):
            self.assertEqual(scan["build"]["with"][matrix_input], "${{ matrix." + matrix_input + " }}")
            self.assertEqual(image["with"][matrix_input], "${{ inputs." + matrix_input + " }}")
            self.assertIn("[0]." + matrix_input, manual["build-rpms"]["with"][matrix_input])

    def test_workflow_boundaries_and_failure_gates(self):
        for name in ("prepare-rpm-sources.yml", "sync-repo-mirror.yml", "rpm-build.yml", "build-okd-stream-coreos.yml"):
            self.assertEqual(set(workflow(name)["on"]), {"workflow_call"})
        sync = workflow("sync-repo-mirror.yml")
        self.assertEqual(len(sync["jobs"]), 1)
        self.assertIn("target_branch", sync["concurrency"]["group"])
        self.assertEqual(sync["name"], "Sync source mirror")
        save = workflow("prepare-rpm-sources.yml")["jobs"]["save-source"]
        self.assertIn("needs.sync.result == 'success'", save["if"])
        builder = workflow("build-okd-stream-coreos.yml")["jobs"]["build-rpms"]
        self.assertNotIn("strategy", builder)
        self.assertNotIn("build_sig", (WORKFLOWS / "rpm-build.yml").read_text())


if __name__ == "__main__":
    unittest.main()
