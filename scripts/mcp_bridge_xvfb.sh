#!/bin/bash
export DISPLAY=:99
exec /opt/venv/bin/python /opt/video_pipeline/scripts/mcp_bridge.py
