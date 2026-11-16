#!/bin/bash
# Deploy/update the home server ("homebox") odoo stack.
#
# Usage, from the repository root:
#     git pull && ./scripts/deploy_homebox.sh
#
# Why not just `up -d`: compose only recreates a container when its config
# changes -- a bind-mounted code update alone leaves the running odoo on old
# code. The explicit `restart` guarantees the workers reload the new source.
set -e

cd "$(dirname "$0")/.."

docker compose -f docker-compose.homebox.yml up -d --remove-orphans
docker compose -f docker-compose.homebox.yml restart odoo

echo "==> deployed. Logs: docker logs -f odoo"
