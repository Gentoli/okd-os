# RPM mirror maintenance walkthrough

Use the attached context as the source of truth for this run's package, source
branch, target branch, worktree, and metadata values. This walkthrough is
package-agnostic; do not assume package-specific compatibility rules.

## Inspect the prepared repository

1. Read the attached JSON context. Note `source_remote`, `source_ref`,
   `mirror_remote`, `target_ref`, `base_sha`, `source_sha`, `spec`, and the
   target metadata fields.
2. In the supplied worktree, inspect `git status`, `git remote -v`, and the
   available refs. The workflow has fetched both branches and checked out the
   mirror branch at `base_sha`.
3. Compare the package spec in `source_ref` with the current mirror version at
   `target_ref`. Substitute the context's actual refs and path in these
   commands; do not type the placeholders literally:

   ```sh
   git diff <target_ref> <source_ref> -- <spec>
   git log --oneline --left-right <target_ref>...<source_ref> -- <spec>
   ```

   Read the upstream spec changes and relevant history so you understand what
   changed, what the mirror already adapts, and which differences are required
   for the target environment.

## Update the mirror

4. Bring the mirrored spec up to date with the selected upstream branch. Retain
   target-environment compatibility changes only when they are still necessary;
   incorporate upstream changes without reverting unrelated updates. Do not add
   speculative changes or alter unrelated files.
5. Create or update `.rpm-mirror.json` with exactly these fields and values from
   the context: `project`, `target_el`, `target_version`, `source_url`,
   `source_branch`, `spec`, and `source_sha`. Use the corresponding context
   value for each field, including the supplied `source_sha`.
6. Stage only the spec named by `spec` and `.rpm-mirror.json`. Create local
   commit(s) on top of `base_sha`, with descriptive commit messages. Do not
   amend, rebase, reset, create merge commits, or push.

## Report the result

7. Obtain the full object IDs of every commit you created, in chronological
   order. Finish your response with one machine-readable line in this exact
   format:

   `COMMIT_OIDS: <full_oid> [<full_oid> ...]`

The workflow will transfer the commits and use the signed-commit action to
publish them. Do not push commits yourself.
