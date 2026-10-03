#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path


def run(*args, cwd=None, check=True):
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def safe_id(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def rpm_identity(spec):
    macros = {}
    for name, value in re.findall(
        r"^%(?:global|define)\s+([A-Za-z0-9_]+)\s+(\S+)",
        spec,
        re.MULTILINE,
    ):
        macros[name] = value

    fields = {}
    for field in ("Name", "Version"):
        match = re.search(
            rf"^{field}:\s*(\S+)", spec, re.MULTILINE
        )
        if match is None:
            raise ValueError(f"spec is missing {field}: field")
        value = match.group(1)
        for _ in range(10):
            expanded = re.sub(
                r"%\{([A-Za-z0-9_]+)\}",
                lambda macro: macros.get(macro.group(1), macro.group(0)),
                value,
            )
            if expanded == value:
                break
            value = expanded
        if "%{" in value:
            raise ValueError(f"cannot resolve RPM {field} value: {value}")
        fields[field.lower()] = value
    return fields["name"], fields["version"]


def source_commits_missing(repo, mirror_ref, source_ref):
    common = run(
        "git", "merge-base", mirror_ref, source_ref,
        cwd=repo,
        check=False,
    )
    if common.returncode != 0:
        return [
            line.split()[1]
            for line in run(
                "git", "rev-list", "--reverse", source_ref, cwd=repo
            ).stdout.splitlines()
        ]

    cherry = run(
        "git", "cherry", mirror_ref, source_ref, cwd=repo
    ).stdout.splitlines()
    return [
        line.split()[1]
        for line in cherry
        if line.startswith("+ ")
    ]


def latest_patch_id(repo, mirror_ref, source_branch):
    messages = run(
        "git", "log", "--format=%B%x00", mirror_ref, cwd=repo
    ).stdout.split("\x00")
    marker = f"PATCH/{source_branch}"
    for message in messages:
        lines = message.strip().splitlines()
        if not lines or lines[0] != marker:
            continue
        for line in lines[1:]:
            if line.startswith("Patch-ID: "):
                return line.removeprefix("Patch-ID: ").strip()
        return ""
    return ""


def check_mirror(row, github_repository):
    if not row["target_branch"].startswith("rpms/"):
        raise ValueError(
            f"mirror branch must be under rpms/: {row['target_branch']}"
        )
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", row["target_branch"]):
        raise ValueError(f"invalid mirror branch: {row['target_branch']}")

    github_url = f"https://github.com/{github_repository}.git"
    source_ref = f"refs/remotes/upstream/{row['source_branch']}"
    mirror_ref = f"refs/remotes/origin/{row['target_branch']}"

    with tempfile.TemporaryDirectory(prefix="rpm-mirror-plan-") as temp:
        repo = Path(temp) / "repo"
        run("git", "init", "--quiet", str(repo))
        run("git", "remote", "add", "upstream", row["source_url"], cwd=repo)
        run(
            "git", "fetch", "--quiet", "--no-tags", "upstream",
            f"refs/heads/{row['source_branch']}:{source_ref}",
            cwd=repo,
        )
        source_sha = run(
            "git", "rev-parse", source_ref, cwd=repo
        ).stdout.strip()
        spec = run(
            "git", "show", f"{source_sha}:{row['spec']}", cwd=repo
        ).stdout
        package_name, source_version = rpm_identity(spec)

        run("git", "remote", "add", "origin", github_url, cwd=repo)
        branch = run(
            "git", "ls-remote", "--heads", "origin",
            f"refs/heads/{row['target_branch']}",
            cwd=repo,
            check=False,
        )
        if branch.returncode != 0:
            raise RuntimeError(
                f"Could not inspect mirror branch {row['target_branch']}: "
                f"{branch.stderr.strip()}"
            )
        target_exists = branch.returncode == 0 and bool(branch.stdout.strip())
        target_sha = ""
        missing_commits = []
        marker_patch_id = ""
        if target_exists:
            run(
                "git", "fetch", "--quiet", "--no-tags", "origin",
                f"refs/heads/{row['target_branch']}:{mirror_ref}",
                cwd=repo,
            )
            target_sha = run(
                "git", "rev-parse", mirror_ref, cwd=repo
            ).stdout.strip()
            missing_commits = source_commits_missing(
                repo, mirror_ref, source_ref
            )
            marker_patch_id = latest_patch_id(
                repo, mirror_ref, row["source_branch"]
            )

    target_version = row.get("target_version") or row["target_el"]
    patch_id = (
        f"source_{safe_id(source_version)}"
        f"_package_{safe_id(package_name)}"
        f"_target_{safe_id(target_version)}"
    )
    return {
        "mirror_id": row["id"],
        "target_branch": row["target_branch"],
        "source_branch": row["source_branch"],
        "source_sha": source_sha,
        "source_version": source_version,
        "package_name": package_name,
        "target_exists": target_exists,
        "target_sha": target_sha,
        "missing_commits": missing_commits,
        "marker_patch_id": marker_patch_id,
        "patch_id": patch_id,
        "needs_sync": (
            not target_exists
            or bool(missing_commits)
            or not marker_patch_id
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--mirror-id", default="all")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text())
    mirrors = plan["mirrors"]
    if args.mirror_id != "all":
        mirrors = [
            row for row in mirrors if row["id"] == args.mirror_id
        ]
        if len(mirrors) != 1:
            raise SystemExit(f"Unknown RPM mirror ID: {args.mirror_id}")

    results = [
        check_mirror(row, args.repository)
        for row in mirrors
    ]
    print(json.dumps(results, separators=(",", ":")))


if __name__ == "__main__":
    main()
