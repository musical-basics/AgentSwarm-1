#!/bin/bash

# Move to the project root directory
cd "$(dirname "$0")"

echo "Booting up the Python Swarm Engine and React UI..."
# Navigate to _v0_frontend and start the Electron application
cd _v0_frontend
pnpm dev
