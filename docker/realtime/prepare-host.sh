#!/usr/bin/env bash
# 宿主机环境预检与配置（部署 Apache Doris BE 前必须执行一次）
set -euo pipefail

echo "[1/3] 检查 CPU AVX2 指令集（Doris 2.1 官方镜像默认要求 AVX2）..."
if grep -q "avx2" /proc/cpuinfo; then
  echo "  OK: 检测到 AVX2 支持"
else
  echo "  WARN: 未检测到 AVX2，请将 docker-compose.realtime.yml 中的 doris-be 镜像替换为 noavx2 版本"
fi

echo "[2/3] 设置 vm.max_map_count = 2000000（Doris BE 硬性要求）..."
sysctl -w vm.max_map_count=2000000
echo "vm.max_map_count=2000000" > /etc/sysctl.d/99-doris.conf

echo "[3/3] 关闭 Swap（Doris BE 启动前要求关闭 swap）..."
swapoff -a || true
echo "  提示：如需重启宿主机后仍保持关闭 swap，请注释 /etc/fstab 中的 swap 行。"

echo "宿主机环境准备完成。"
