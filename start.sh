#!/bin/bash

# Move to the project root directory
cd "$(dirname "$0")"

echo "Booting up the Python Swarm Engine and React UI..."

# Kill any stale process on port 6500 (backend)
OLDPID=$(lsof -ti:6500 2>/dev/null)
if [ -n "$OLDPID" ]; then
  echo "Killing stale process on port 6500 (PID: $OLDPID)"
  kill -9 $OLDPID 2>/dev/null
fi

# Navigate to _v0_frontend and start the Electron application
cd "_v0_frontend"
pnpm dev
