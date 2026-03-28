# Bug Fix Notes: Flowmind IDE

---

## Bug #1: Port Already In Use / Open Folder Button Not Working

**Date:** 2026-03-28

### Symptoms
- `./start.sh` fails with: `[Errno 48] error while attempting to bind on address ('127.0.0.1', 8765): [errno 48] address already in use`
- Python backend exits immediately with code 1
- WebSocket never connects → `socketRef.readyState: undefined`
- Clicking "Open Folder" shows: `[OpenFolder] Aborted - folderPath: /path/to/folder socketRef.readyState: undefined`
- File tree shows default placeholder files instead of actual workspace

### Root Cause
**Three compounding issues:**

1. **Electron spawns its own Python backend** via `electron/main.cjs → createPythonBackend()`. This means the backend is launched by Electron itself — NOT by `start.sh`. If the previous Electron window didn't fully quit (e.g. Ctrl+C only kills the shell, not the Electron subprocess tree), the Python process stays alive and holds port 8765 / 6500.

2. **Stale React closure on `socket` state**: The `handleOpenFolder` function (and other button handlers) captured the `socket` state variable at mount time, before the WebSocket had connected. Since state updates are async in React, any handler defined with a closure over `socket` would always see `undefined` until the component re-renders and the closure is recreated.

3. **`lsof | xargs kill` fails on macOS when port is empty**: When no process holds the port, `lsof` returns nothing and `xargs kill -9` with empty input throws an error on macOS (GNU `xargs -r` flag not available).

### Failed Fixes Attempted
1. Adding `lsof -ti:8765 | xargs kill -9 2>/dev/null || true` to `start.sh` — failed because `xargs` on macOS errored on empty input, producing `ull: command not found` (truncated error)
2. Replacing `socket` state with a `useRef(null)` socketRef — fixed the closure issue, but the backend was still not starting because port was still held by the old Electron process

### Final Solution

**1. Port management moved into `electron/main.cjs`** (the actual backend spawner):
```javascript
function killPort(port) {
  try {
    const { execSync } = require('child_process');
    const pid = execSync(`lsof -ti:${port} 2>/dev/null`, { encoding: 'utf8' }).trim();
    if (pid) execSync(`kill -9 ${pid} 2>/dev/null`);
  } catch (e) { /* safe ignore */ }
}
// Called before spawn:
killPort(6500);
```

**2. Port changed from 8765 → 6500** to avoid conflict with other services on the machine.

**3. `socketRef` pattern for all WebSocket sends**:
```tsx
const socketRef = useRef<WebSocket | null>(null);
// Set on connect:
ws.onopen = () => { setSocket(ws); socketRef.current = ws; };
// Use in all callbacks:
socketRef.current?.send(JSON.stringify(...));
```

**4. macOS-safe port kill in `start.sh`**:
```bash
OLDPID=$(lsof -ti:6500 2>/dev/null)
if [ -n "$OLDPID" ]; then kill -9 $OLDPID; fi
```

### Ports In Use
| Service | Port |
|---------|------|
| Next.js / Electron frontend | 3008 |
| FastAPI / Python backend (WebSocket) | **6500** |

### Key Files
- `backend/main.py` line `uvicorn.run(...)` — backend port
- `_v0_frontend/components/flowmind/flowmind-ide.tsx` — `/ws` WebSocket URL  
- `_v0_frontend/components/flowmind/terminal-panel.tsx` — `/pty` WebSocket URL
- `_v0_frontend/electron/main.cjs` — Electron process manager + Python backend spawner
- `start.sh` — Shell launcher (kills stale process, then runs pnpm dev)
