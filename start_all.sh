#!/usr/bin/env bash
# 一键启动收银员的全部服务。
# 用法：双击不行的话，终端里 ./start_all.sh
# 全部停止：按 Ctrl+C
set -u

cd "$(dirname "$0")"

echo "=============================================="
echo " AI 收银员 · 启动服务"
echo "=============================================="

cleanup() {
    echo
    echo "正在停止所有服务…"
    kill 0 2>/dev/null
    exit 0
}
trap cleanup INT TERM

echo "① 商户后台        http://127.0.0.1:8800"
python3 app/admin.py &

echo "② 设备桥接        本地商品库 <-> 小智云端（内含屏幕推图服务 :8801）"
./run_bridge.sh &

if [ "${1:-}" = "--greet" ]; then
    echo "③ 摄像头迎宾      检测到顾客进门自动打招呼（第一次要给摄像头权限）"
    python3 app/vision.py &
else
    echo "③ 摄像头迎宾      未启动（./start_all.sh --greet 开启）"
fi

echo "=============================================="
echo " 按 Ctrl+C 停止全部"
echo "=============================================="
wait
