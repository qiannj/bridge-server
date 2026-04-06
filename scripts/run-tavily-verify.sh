#!/bin/bash
# Tavily 验证脚本启动器

export TAVILY_API_KEY="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"

cd /home/pi/.openclaw/workspace/bridge-server-product
python3 scripts/verify-with-tavily.py
