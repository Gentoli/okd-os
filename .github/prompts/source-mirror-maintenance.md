# Maintain one source mirror

Follow the JSON run context and any attached recipe or repository instructions.
All names come from that context. Work in the supplied worktree. The workflow
has configured the `mirror-upstream` and `mirror-target` remotes, fetched
`source_ref`, and fetched `target_ref` if the mirror exists. Repository
instructions appended below take precedence for repository-specific
requirements.

1. Inspect the source repository, its current refs, and its history. Use the
   repository instructions and evidence from comparable target and source
   branches to identify necessary compatibility changes. Do not assume one file
   carries all compatibility behavior.
2. If `target_ref` is null, checkout a local branch at `source_ref`. Create
   `.mirror-patch.json` with the identity described below, and commit it with
   the exact subject `PATCH/<source_branch>`. This must be the first commit
   after the upstream base. Develop target compatibility changes using the
   repository instructions and commit those changes after the marker.
3. If the mirror exists, find its `PATCH/` marker and read its committed
   `.mirror-patch.json`. Identify the old upstream base as the marker's parent.
   Inspect all compatibility commits after that base. Checkout a local branch
   at the current `source_ref`, recreate the identity commit first, then
   cherry-pick the compatibility commits in order (or rebase the stack onto the
   current upstream base). Resolve conflicts and revise adaptations when
   upstream changes require it. Do not merge upstream, append a snapshot of its
   files, or discard unrelated upstream updates. If an older mirror lacks the
   marker, inspect its history and recreate its necessary adaptations on the
   current source base using the same procedure.
4. In the first commit after upstream, `.mirror-patch.json` must contain:

   ```json
   {
     "id": "<patch_id>",
     "project": "<project>",
     "source_url": "<source_url>",
     "source_branch": "<source_branch>"
   }
   ```

   Substitute the JSON context values. Do not add a source SHA or a package
   `Release:` to the identity. The marker commit contains the identity file; it
   need not be empty. Keep compatibility changes in the subsequent commits so
   future updates can replay them independently.
5. Preserve upstream provenance and source archives with their upstream
   identity. Do not invent compatibility patches for unaffected files. Keep the
   full current source history underneath the patch stack.
6. Create ordinary local commits, including the new or recreated marker, and
   keep the history linear. Do not create merge commits, push, invoke GitHub
   write APIs, sign commits, or modify the workflow repository. The workflow
   publishes your commits through the signing action and does not validate
   compatibility content.
7. Commit the prepared stack to the local `mirror-patch` branch, beginning with
   the marker and ending with the final compatibility change. Do not push.

An invoked update must produce the identity commit even if no compatibility
changes are needed.
