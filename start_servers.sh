#!/bin/bash
# Start both VPS servers with shared JWT secret from .env
set -e

export $(grep -v '^#' /opt/video_pipeline/.env | xargs)

cd /opt/video_pipeline
nohup /opt/venv/bin/python review_server.py >> /tmp/review_server.log 2>&1 &

cd /opt/video_pipeline/vybord-user-api
nohup /opt/venv/bin/python main.py >> /tmp/user_api.log 2>&1 &

echo "Started review_server (7073) and user_api (8001)"
