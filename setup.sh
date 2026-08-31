#!/bin/bash
# M2U4OC Setup Script
# Usage: ./setup.sh /path/to/openclaw/workspace

set -e

WORKSPACE="${1:-./workspace}"

echo "========================================="
echo "M2U4OC - Memory Agent Setup"
echo "========================================="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 required"
    exit 1
fi

# Create workspace if needed
mkdir -p "$WORKSPACE"

# Copy memory agent
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/memory_agent.py" "$WORKSPACE/"

# Initialize memory system
echo "Initializing memory system..."
python3 "$WORKSPACE/memory_agent.py" "$WORKSPACE"

echo ""
echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo ""
echo "Files created in $WORKSPACE:"
echo "  - MEMORY.md"
echo "  - SOUL.md" 
echo "  - USER.md"
echo "  - memory/"
echo ""
echo "Next steps:"
echo "1. Edit SOUL.md - Define your agent's personality"
echo "2. Edit USER.md - Add user preferences"
echo "3. Add to your system prompt (see README.md)"
echo ""
