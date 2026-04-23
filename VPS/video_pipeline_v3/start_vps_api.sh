#!/bin/bash
cd /opt/video_pipeline_v3
source .env 2>/dev/null
exec /opt/venv/bin/python scripts/vps_api.py >> /tmp/v3_vps_api.log 2>&1
