Maintain the RPM mirror described by the attached JSON context. Read the
package spec and upstream changes before editing.

Missing upstream commits have already been cherry-picked when possible. If a
cherry-pick is in progress, resolve conflicts while preserving upstream changes
and finish it with `git add` and `git cherry-pick --continue`. Confirm that
every upstream commit is represented before finishing.

Recreate only compatibility changes required for the target EL. For CRI-O on
EL9, preserve the `containernetworking-plugins` suggestion and the
`%{_libexecdir}/cni` plugin directory. For every mirrored package, set the RPM
`Release:` to the upstream release plus exactly
`.fallback.<patch_id>`, before any `%{?dist}` macro. Remove an existing
`.fallback.` suffix before replacing it. This deterministic release patch is
required even when no functional EL compatibility change is needed.

Do not invent other compatibility changes, alter `.rpm-mirror.json`, modify
repository workflows, or push commits. Leave compatibility edits in the
worktree; the workflow will create and publish signed commits.
