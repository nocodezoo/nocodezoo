#!/bin/bash
# V3.1 Startup Script — Vybord on Supabase

export USER_API_PORT=18001
export SUPABASE_URL=http://95.111.236.104:54341
export SUPABASE_KEY=YOUR_SUPABASE_KEY_HERE
export SUPABASE_SERVICE_KEY=YOUR_SUPABASE_SERVICE_KEY_HERE
export SUPABASE_DB_URL=postgresql://postgres:YOUR_PASSWORD@YOUR_HOST:54342/postgres
export JWT_SECRET=YOUR_JWT_SECRET_HERE

cd /opt/video_pipeline_v3

# Start Supabase v3 (Docker containers)
cd /opt/video_pipeline_v3 && supabase start -x studio --network-id supabase_v3_net 2>/dev/null || echo "Supabase already running"

sleep 3

# Start user_api V3.1 (Supabase-backed, replaces main.py)
nohup /opt/venv/bin/python user_api.py >> /tmp/v3_user_api.log 2>&1 &

# Start V3 pipeline servers
nohup /opt/venv/bin/python review_server.py >> /tmp/v3_review.log 2>&1 &
nohup /opt/venv/bin/python lookup_server.py >> /tmp/v3_lookup.log 2>&1 &
nohup /opt/venv/bin/python scripts/vps_api.py >> /tmp/v3_vps_api.log 2>&1 &

echo "V3.1 started"
echo "Ports: 17073 (review), 17074 (lookup), 18000 (vps_api), 18001 (user_api)"
echo "Supabase: 54341 (API), 54342 (DB)"
