#!/usr/bin/env bash
# L08 第 2 步：两个训练任务 A、B 的 worker 交替提交（A0 B0 A1 B1 A2 B2），模拟"两个任务同时到达"。
# 不用任何排队工具，直接交给 k8s 默认调度器——它一个 Pod 一个 Pod 地调度。
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

for idx in 0 1 2; do
  for job in a b; do
    sed -e "s/__JOB__/${job}/g" -e "s/__IDX__/${idx}/g" "$here/worker-pod.yaml.tmpl" | kubectl apply -f -
    sleep 1   # 让调度器按提交顺序逐个处理
  done
done
