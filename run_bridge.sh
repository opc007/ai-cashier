#!/usr/bin/env bash
# 把本地收银员 MCP 服务桥接到小智云端。
#
# 用法一（直接传地址）：
#   ./run_bridge.sh "wss://api.xiaozhi.me/mcp/?token=xxxxx"
#
# 用法二（写进 .env，不用每次传）：
#   echo 'MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=xxxxx' > .env
#   ./run_bridge.sh
set -euo pipefail

cd "$(dirname "$0")"

ENDPOINT="${1:-}"

# 没传参数时，让 mcp_pipe.py 自己从 .env 读
if [ -n "$ENDPOINT" ]; then
    export MCP_ENDPOINT="$ENDPOINT"
fi

if [ -z "${MCP_ENDPOINT:-}" ] && [ ! -f .env ]; then
    echo "缺少 MCP 接入点地址。"
    echo
    echo "  用法: ./run_bridge.sh \"wss://api.xiaozhi.me/mcp/?token=...\""
    echo "  或者: echo 'MCP_ENDPOINT=wss://...' > .env  然后  ./run_bridge.sh"
    exit 1
fi

echo "启动桥接：本地 MCP 服务 -> 小智云端"
exec python3 -u bridge/mcp_pipe.py app/mcp_server.py
