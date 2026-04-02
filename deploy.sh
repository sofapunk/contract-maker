#!/bin/bash
# Deploy script — run on the Hetzner server
# Usage: bash deploy.sh

set -e

echo "=== Contract Maker — Deploy ==="

# Check prerequisites
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not installed."
    exit 1
fi

if [ ! -f .secrets/creative-strategy-clode-f15c21f08fd2.json ]; then
    echo "❌ Google service account JSON missing in .secrets/"
    echo "   Copy the file from the everything-watcher .secrets/ folder:"
    echo "   cp ../everything-watcher/.secrets/creative-strategy-clode-f15c21f08fd2.json .secrets/"
    exit 1
fi

# Create shared network if it doesn't exist
docker network create caddy-shared 2>/dev/null || true

echo "✅ Prerequisites OK"
echo "🔨 Building and starting container..."

docker compose up -d --build

echo ""
echo "✅ Deployed! Check status with:"
echo "   docker compose logs -f web"
echo ""
echo "⚠️  Make sure the everything-watcher Caddy is updated:"
echo "   1. Add contracts.sofapunks.de to the Caddyfile"
echo "   2. Add caddy-shared network to the watcher docker-compose.yml"
echo "   3. Restart watcher caddy: cd ../everything-watcher && docker compose restart caddy"
