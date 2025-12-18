#!/bin/bash
set -e

echo "==================================="
echo "Monarch Ingestor Container Starting"
echo "==================================="

# Run database initialization
python scripts/init_db.py

echo ""
echo "Container ready! You can now:"
echo "  - Exec into this container from Portainer"
echo "  - Run: python scripts/fetch_observations.py -n 20"
echo "  - Run: python scripts/sync_to_labelstudio.py -n 50"
echo ""

# Keep container running
exec sleep infinity
