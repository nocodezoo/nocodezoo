#!/bin/bash
cd /opt/video_pipeline_v3
source .env 2>/dev/null
exec /opt/venv/bin/python lookup_server.py >> /tmp/v3_lookup.log 2>&1
