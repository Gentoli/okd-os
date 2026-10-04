# Maintain one OKD OS source mirror

Work only in the supplied worktree and follow the JSON run context. The
workflow has fetched `source_ref`; `target_ref` is set only when the target
mirror branch already exists. The workflow signs and publishes your commits.
Do not push or call GitHub write APIs.

1. Inspect the source tree and relevant history. For an existing mirror,
   inspect `identity_file` and the compatibility commits after its parent. Do
   not copy snapshots of upstream files or merge upstream history.
2. Start a local branch at `source_ref`. Create or recreate `identity_file` as
   the first commit after upstream, with JSON fields `id`, `project`,
   `source_url`, `source_branch`, `target_branch`, and `target_version` from
   the run context. Set `id` to the context's `patch_id`, and use JSON null for
   `target_version` when the source is not versioned. The first commit subject
   must be exactly `PATCH/<source_branch>`.
3. For the initial `coreos/rhel-coreos-config` mirror only, apply the tracked
   `seed_patch` from `GITHUB_WORKSPACE` to the worktree and commit it after the
   marker. Do not apply it again on updates; replay the compatibility commit
   from `target_ref` instead.
4. For `openshift/os` target version 4.22:
   - Restore the `centos-9` conditional in `packages-openshift.yaml` while
     preserving the existing 4.22 package requirements and postprocessing.
   - Use `reference_ref` as the reference for the CentOS 9 conditional and
     `c9s.repo` repository IDs. Define the EL9 BaseOS, AppStream, and
     appropriate NFV repositories, plus the local repository used for the
     built 4.22 RPMs. Do not carry over the 4.20 Cloud SIG repository as the
     source of 4.22 runtime packages.
   - Update `build-node-image.sh` repository-file selection so
     `osversion=centos-9` loads `c9s.repo`, while CentOS 10 continues to load
     `c10s.repo`.
   - Do not modify `build-node-image.sh` for the local built-RPM allowlist;
     the caller workflow handles that local repository configuration.
   Other target versions receive an identity marker only unless their run
   context explicitly includes a compatibility change.
5. For an update, start from the current `source_ref`, recreate the marker,
   then replay compatibility commits in order. Resolve conflicts using current
   upstream, revise obsolete adaptations, and retain unrelated upstream
   changes. Keep the stack linear and do not create merge commits.
6. Run `git diff --check`, create ordinary local commits, and report every
   commit in the new stack from marker through final adaptation, in order.
   Finish with exactly one machine-readable line:

   ```text
   COMMIT_OIDS: <full-commit-id> <full-commit-id>
   ```

   Use actual full hexadecimal IDs and omit angle brackets. Never report
   `NONE` when the mirror is absent or upstream has advanced.
