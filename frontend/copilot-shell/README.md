# Copilot Shell

React + TypeScript embeddable Copilot UI built with assistant-ui and Microsoft Fluent UI.

```powershell
pnpm install
pnpm build
```

The Gateway serves the build at `http://127.0.0.1:8765/copilot-shell/` for iframe or desktop WebView embedding.

For standalone UI development with API proxying:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ..\..\scripts\start-copilot-shell.ps1 -GatewayUrl http://127.0.0.1:8765
```
