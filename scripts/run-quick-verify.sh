#!/bin/bash
# Provider 快速核对工具启动器

export TAVILY_API_KEY="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"

cd /home/pi/.openclaw/workspace/bridge-server-product
python3 scripts/quick-verify.py
