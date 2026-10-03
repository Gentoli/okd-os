#!/usr/bin/env python3

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


PROJECTS = ("cri-o", "cri-tools", "conmon-rs")


def run(*args, cwd=None, check=True):
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def remote_has_branch(url, branch):
    result = run(
        "git", "ls-remote", "--heads", url, f"refs/heads/{branch}",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not inspect {url} branch {branch}: "
            f"{result.stderr.strip()}"
        )
    return bool(result.stdout.strip())


def mirror_metadata(url, branch, metadata_file):
    with tempfile.TemporaryDirectory(prefix="rpm-source-plan-") as temp:
        repo = Path(temp) / "repo"
        run("git", "init", "--quiet", str(repo))
        run("git", "remote", "add", "origin", url, cwd=repo)
        run(
            "git", "fetch", "--quiet", "--no-tags", "origin",
            f"refs/heads/{branch}:refs/remotes/origin/mirror",
            cwd=repo,
        )
        return json.loads(
            run(
                "git", "show",
                f"refs/remotes/origin/mirror:{metadata_file}",
                cwd=repo,
            ).stdout
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--okd-version", required=True)
    parser.add_argument("--os-version", required=True)
    parser.add_argument("--repository", default="Gentoli/okd-os")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text())
    targets = [
        target
        for target in plan["build_targets"]
        if target["okd_version"] == args.okd_version
        and str(target["os_version"]) == args.os_version
    ]
    if len(targets) != 1:
        raise SystemExit(
            f"No unique RPM target for OKD {args.okd_version} "
            f"EL{args.os_version}."
        )

    sources = plan["sources"]
    result = {}
    for project in PROJECTS:
        upstream_url = sources["upstream_url_pattern"].format(
            project=project
        )
        source_pattern = sources["branch_patterns"][project][args.os_version]
        source_branch = source_pattern.format(
            project=project,
            os_version=args.os_version,
            okd_version=args.okd_version,
        )
        shared_source_pattern = sources.get(
            "shared_branch_patterns", {}
        ).get(project, {}).get(args.os_version)
        shared_mirror = shared_source_pattern is not None
        branch_version = (
            f"el{args.os_version}" if shared_mirror else args.okd_version
        )
        mirror_pattern = sources["mirror_branch_patterns"][
            "shared" if shared_mirror else "okd_release"
        ]
        mirror_branch = mirror_pattern.format(
            project=project,
            os_version=args.os_version,
            okd_version=branch_version,
        )
        mirror_url = sources["mirror_url_pattern"].format(
            repository=args.repository
        )
        if remote_has_branch(mirror_url, mirror_branch):
            metadata = mirror_metadata(
                mirror_url, mirror_branch, sources["metadata_file"]
            )
            expected = (
                project,
                args.os_version,
                branch_version,
            )
            actual = (
                metadata.get("project"),
                str(metadata.get("target_el")),
                metadata.get("target_version"),
            )
            if actual != expected:
                raise ValueError(
                    f"Mirror metadata on {mirror_branch} does not match "
                    "the requested build target."
                )
            result[project] = {
                "url": mirror_url,
                "branch": mirror_branch,
            }
        elif remote_has_branch(upstream_url, source_branch):
            result[project] = {
                "url": upstream_url,
                "branch": source_branch,
            }
        else:
            raise SystemExit(
                f"Missing {project} source for OKD {args.okd_version} "
                f"EL{args.os_version}; run the RPM mirror planner first."
            )
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
