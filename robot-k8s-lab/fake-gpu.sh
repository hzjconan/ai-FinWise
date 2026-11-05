#!/usr/bin/env bash
# L08 第 1 步：给每个 worker 节点"报"4 张模拟 GPU。
#
# 原理：nvidia.com/gpu 在 k8s 看来只是一个"扩展资源"（extended resource）——一个可计数的名字。
# 真实集群里由 NVIDIA device plugin 上报；这里直接 PATCH 节点的 status.capacity，调度器就会按它记账。
# 没有真实设备：Pod 能申请、能被调度和计数，但容器里拿不到任何 GPU。
#
#   bash robot-k8s-lab/fake-gpu.sh          # 默认每台 4 张
#   GPUS_PER_NODE=2 bash robot-k8s-lab/fake-gpu.sh
set -euo pipefail

GPUS_PER_NODE="${GPUS_PER_NODE:-4}"

for node in $(kubectl get nodes -l '!node-role.kubernetes.io/control-plane' -o name); do
  # JSON Patch 路径里的 "/" 要转义成 "~1"：nvidia.com/gpu → nvidia.com~1gpu
  kubectl patch "$node" --subresource=status --type=json \
    -p "[{\"op\":\"add\",\"path\":\"/status/capacity/nvidia.com~1gpu\",\"value\":\"${GPUS_PER_NODE}\"}]" >/dev/null
  echo "${node#node/}: nvidia.com/gpu=${GPUS_PER_NODE}"
done

# allocatable（调度器真正看的值）由 kubelet 在下一次上报节点状态时根据 capacity 算出，要等几秒
echo
echo "等待 kubelet 同步 allocatable ..."
for _ in $(seq 1 30); do
  missing=$(kubectl get nodes -l '!node-role.kubernetes.io/control-plane' \
    -o jsonpath='{range .items[*]}{.status.allocatable.nvidia\.com/gpu}{"\n"}{end}' | grep -c '^$' || true)
  [ "$missing" = "0" ] && break
  sleep 2
done

kubectl get nodes -o custom-columns='NODE:.metadata.name,GPU(capacity):.status.capacity.nvidia\.com/gpu,GPU(allocatable):.status.allocatable.nvidia\.com/gpu'
