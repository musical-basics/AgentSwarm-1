#!/bin/bash

# Move to the project root directory
cd "$(dirname "$0")"

echo "Booting up the Python Swarm Engine and React UI..."

# Kill any stale process on port 8765 (backend)
PID=$(lsof -ti:8765 2>/dev/null); [ -n "$PID" ] && kill -9 $PID 2>/dev/null; true

# Navigate to _v0_frontend and start the Electron application
cd _v0_frontend
pnpm dev
