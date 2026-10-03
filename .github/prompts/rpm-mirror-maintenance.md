Maintain the RPM mirror described by the attached JSON context. The workflow
has fetched the upstream and mirror branches and configured their remotes and
refs in the attached worktree.

Compare the mirror worktree with `source_ref` and update only the package spec
and `.rpm-mirror.json`. Bring the spec forward to the current upstream version,
preserving upstream changes while applying only compatibility edits required
for the target EL. For CRI-O on EL9, preserve the `containernetworking-plugins`
suggestion and `%{_libexecdir}/cni` plugin directory.

Update `.rpm-mirror.json` with exactly these fields: `project`, `target_el`,
`target_version`, `source_url`, `source_branch`, `spec`, and `source_sha`.
Set `source_sha` to the commit at `source_ref`. Do not use a deterministic
`Release:` suffix or otherwise change `Release:` solely to identify the mirror.

Do not modify files other than the package spec and `.rpm-mirror.json`. Do not
stage, commit, push, force-push, or modify workflow or prompt files. The
workflow validates and stages your changes, then creates and publishes the
signed commit.
