#!/usr/bin/env python3

import argparse
import json
import re
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


def safe_id(value):
    return re.sub(r"[^A-Za-z0-9_.]+", "_", value)


def rpm_identity(spec):
    macros = dict(
        re.findall(
            r"^%(?:global|define)\s+([A-Za-z0-9_]+)\s+(\S+)",
            spec,
            re.MULTILINE,
        )
    )
    fields = {}
    for field in ("Name", "Version"):
        match = re.search(rf"^{field}:\s*(\S+)", spec, re.MULTILINE)
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


def remote_sha(repo_url, branch):
    result = run(
        "git", "ls-remote", "--heads", repo_url,
        f"refs/heads/{branch}",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not inspect {repo_url} branch {branch}: "
            f"{result.stderr.strip()}"
        )
    return result.stdout.split()[0] if result.stdout.strip() else ""


def format_pattern(pattern, project, os_version, okd_version):
    return pattern.format(
        project=project,
        os_version=os_version,
        okd_version=okd_version,
    )


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
    return [line.split()[1] for line in cherry if line.startswith("+ ")]


def marker_patch_id(repo, mirror_ref, source_branch):
    messages = run(
        "git", "log", "--format=%B%x00", mirror_ref, cwd=repo
    ).stdout.split("\x00")
    marker = f"PATCH/{source_branch}"
    for message in messages:
        lines = message.strip().splitlines()
        if lines and lines[0] == marker:
            for line in lines[1:]:
                if line.startswith("Patch-ID: "):
                    return line.removeprefix("Patch-ID: ").strip()
            return ""
    return ""


def read_branch_metadata(repo, ref, metadata_path):
    result = run(
        "git", "show", f"{ref}:{metadata_path}",
        cwd=repo,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"Mirror branch {ref} has no {metadata_path} metadata."
        )
    metadata = json.loads(result.stdout)
    required = {
        "project",
        "target_el",
        "target_version",
        "source_url",
        "source_branch",
        "spec",
    }
    missing = required - metadata.keys()
    if missing:
        raise ValueError(
            f"Mirror metadata {metadata_path} is missing: "
            + ", ".join(sorted(missing))
        )
    return metadata


def inspect_mirror(row, github_repository, metadata_path):
    target_branch = row["target_branch"]
    if not target_branch.startswith("rpms/") or not re.fullmatch(
        r"[A-Za-z0-9._/-]+", target_branch
    ):
        raise ValueError(f"invalid mirror branch: {target_branch}")

    source_ref = f"refs/remotes/upstream/{row['source_branch']}"
    mirror_ref = f"refs/remotes/origin/{target_branch}"
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
        spec_text = run(
            "git", "show", f"{source_sha}:{row['spec']}", cwd=repo
        ).stdout
        package_name, source_version = rpm_identity(spec_text)

        run(
            "git", "remote", "add", "origin",
            f"https://github.com/{github_repository}.git",
            cwd=repo,
        )
        target_sha = remote_sha(
            f"https://github.com/{github_repository}.git", target_branch
        )
        missing_commits = []
        existing_patch_id = ""
        if target_sha:
            run(
                "git", "fetch", "--quiet", "--no-tags", "origin",
                f"refs/heads/{target_branch}:{mirror_ref}",
                cwd=repo,
            )
            metadata = read_branch_metadata(repo, mirror_ref, metadata_path)
            expected_metadata = (
                row["project"],
                row["target_el"],
                row["target_version"],
                row["source_url"],
                row["source_branch"],
                row["spec"],
            )
            actual_metadata = (
                metadata["project"],
                str(metadata["target_el"]),
                metadata["target_version"],
                metadata["source_url"],
                metadata["source_branch"],
                metadata["spec"],
            )
            if actual_metadata != expected_metadata:
                raise ValueError(
                    f"Metadata on {target_branch} does not match the "
                    "requested mirror source."
                )
            missing_commits = source_commits_missing(
                repo, mirror_ref, source_ref
            )
            existing_patch_id = marker_patch_id(
                repo, mirror_ref, row["source_branch"]
            )

    patch_id = (
        f"source_{safe_id(source_version)}"
        f"_package_{safe_id(package_name)}"
        f"_target_{safe_id(row['target_version'])}"
    )
    return {
        **row,
        "source_sha": source_sha,
        "source_version": source_version,
        "package_name": package_name,
        "target_exists": bool(target_sha),
        "target_sha": target_sha,
        "missing_commits": missing_commits,
        "marker_patch_id": existing_patch_id,
        "patch_id": patch_id,
        "needs_sync": (
            not target_sha or bool(missing_commits) or not existing_patch_id
        ),
    }


def mirror_rows(plan, okd_version):
    sources = plan["sources"]
    requested_targets = [
        target
        for target in plan["build_targets"]
        if okd_version is None or target["okd_version"] == okd_version
    ]
    rows = []
    for target in requested_targets:
        version = target["okd_version"]
        os_version = str(target["os_version"])
        for project in PROJECTS:
            source_url = sources["upstream_url_pattern"].format(
                project=project
            )
            branch_pattern = sources["branch_patterns"][project][os_version]
            direct_branch = format_pattern(
                branch_pattern, project, os_version, version
            )
            mirror_branch = format_pattern(
                sources["mirror_branch_patterns"]["okd_release"],
                project,
                os_version,
                version,
            )
            mirror_url = sources["mirror_url"]
            target_sha = remote_sha(mirror_url, mirror_branch)
            if target_sha:
                with tempfile.TemporaryDirectory(
                    prefix="rpm-mirror-metadata-"
                ) as temp:
                    repo = Path(temp) / "repo"
                    run("git", "init", "--quiet", str(repo))
                    run("git", "remote", "add", "origin", mirror_url, cwd=repo)
                    mirror_ref = "refs/remotes/origin/mirror"
                    run(
                        "git", "fetch", "--quiet", "--no-tags", "origin",
                        f"refs/heads/{mirror_branch}:{mirror_ref}",
                        cwd=repo,
                    )
                    metadata = read_branch_metadata(
                        repo, mirror_ref, sources["metadata_file"]
                    )
                row = {
                    "id": f"{project}-el{os_version}-{version}",
                    "project": project,
                    "target_el": os_version,
                    "target_version": version,
                    "source_url": metadata["source_url"],
                    "source_branch": metadata["source_branch"],
                    "target_branch": mirror_branch,
                    "spec": metadata["spec"],
                }
                rows.append(
                    inspect_mirror(
                        row, "Gentoli/okd-os", sources["metadata_file"]
                    )
                )
                continue

            if remote_sha(source_url, direct_branch):
                continue

            fallback_pattern = sources.get(
                "fallback_branch_patterns", {}
            ).get(project, {}).get(os_version)
            if fallback_pattern is None:
                raise ValueError(
                    f"No exact source branch or fallback for "
                    f"{project} EL{os_version} OKD {version}."
                )
            source_branch = format_pattern(
                fallback_pattern, project, os_version, version
            )
            if not remote_sha(source_url, source_branch):
                raise ValueError(
                    f"Fallback source branch is missing: "
                    f"{project}:{source_branch}"
                )
            row = {
                "id": f"{project}-el{os_version}-{version}",
                "project": project,
                "target_el": os_version,
                "target_version": version,
                "source_url": source_url,
                "source_branch": source_branch,
                "target_branch": mirror_branch,
                "spec": format_pattern(
                    sources["spec_pattern"],
                    project,
                    os_version,
                    version,
                ),
            }
            rows.append(
                inspect_mirror(
                    row, "Gentoli/okd-os", sources["metadata_file"]
                )
            )
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--repository", default="Gentoli/okd-os")
    parser.add_argument("--okd-version")
    parser.add_argument("--needs-sync-only", action="store_true")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text())
    rows = mirror_rows(plan, args.okd_version)
    if args.needs_sync_only:
        rows = [row for row in rows if row["needs_sync"]]
    print(json.dumps(rows, separators=(",", ":")))


if __name__ == "__main__":
    main()
