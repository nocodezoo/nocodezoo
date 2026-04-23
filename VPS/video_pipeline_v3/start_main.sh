#!/bin/bash
cd /opt/video_pipeline_v3
source .env 2>/dev/null
exec /opt/venv/bin/python main.py >> /tmp/v3_main.log 2>&1
