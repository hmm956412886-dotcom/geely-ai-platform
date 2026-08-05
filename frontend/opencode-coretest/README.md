# CoreTest Agent OpenCode UI

This directory contains the auditable CoreTest Profile applied to the locked
OpenCode Web UI. It does not contain a second chat implementation.

Upstream source archives, the frozen dependency lockfile, tested Node/pnpm
versions, and their hashes are recorded in `third_party/OpenCode-UI-SOURCE.json`.
Build the profile with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-opencode-ui.ps1
```

The build extracts immutable upstream sources into `tmp/`, applies the files in
`profile/`, and writes the static product to `frontend/opencode-coretest/dist`.
The AI Gateway serves that product for `/agent-native/` and continues to proxy
the restricted OpenCode HTTP/SSE protocol.

CoreTest Profile intentionally keeps OpenCode sessions, tool activity,
questions, permissions, retry, todo, Markdown, Diff, revert, fork, compact, and
file references. Server management, arbitrary project selection, PTY, sharing,
OAuth, arbitrary providers, and external provider documentation are outside the
product surface and are also blocked by the Gateway protocol allowlist.
