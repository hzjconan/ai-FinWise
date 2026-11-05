# robot-k8s-lab — k8s 训练调度实验环境

L08（机器人数据面试第二阶段 · 专题 D：k8s 训练调度）的动手环境，隔离于 `backend/`（同 `langgraph-lab/`、`mcp-lab/` 做法）。

- **集群**：kind（Kubernetes in Docker），1 控制面 + 4 worker，每个 worker 模拟 4 张 GPU，共 16 张（面试场景"8 台 × 4 卡"的缩小版）。
- **GPU 是模拟的**：只 PATCH 节点的扩展资源 `nvidia.com/gpu`，调度和计数是真的，容器里没有真实 GPU。所以能练调度、配额、抢占、碎片，**练不了** NVLink 速度、MIG、真实训练吞吐。
- **前置**：Docker Desktop 已启动；`kind`、`kubectl`、`helm` 已装。
- **讲义**：`docs/ai-agent-learning/lessons/L08-k8s-training-scheduling.md`。

## 文件
- `kind-cluster.yaml` — 集群定义（1 + 4 节点）。
- `fake-gpu.sh` — 给每个 worker 上报模拟 GPU。
- `show_jobs.py` — 按训练任务汇总 worker 到齐情况和 GPU 占用（所有实验 Pod 都带 `lab=l08`、`train-job` 标签）。
- `step2/` — 第 2 步：`worker-pod.yaml.tmpl`（worker 模板，含 TODO）+ `submit-interleaved.sh`（A、B 两个任务交替提交给默认调度器）。
- `step3/` — Kueue 队列配置和训练 Job 模板（含 parallelism 练习）。此步用 Job / Workload 查询整体排队状态；`show_jobs.py` 只统计已有 Pod，无法显示尚未创建 Pod 的排队 Job。
- `step4/queues.yaml` — 甲乙各 8 卡、最多借入 / 借出 4 卡的共享队列。切换前必须退出 step3 的实验任务并移除其旧队列，避免把同一批 16 张物理卡重复计入独立配额。
- `step4/team-a-job.yaml` — 甲的 12 卡模拟训练任务；通过 `team-a-queue` 提交，观察 ClusterQueue 状态中的 `total: 12` 和 `borrowed: 4`。
- `step4/team-b-job.yaml` — 乙的 8 卡模拟训练任务；甲借用期间提交，观察禁用回收抢占时的整体排队。
- `step5/reclaim-team-b.yaml` — merge patch，将乙的 `reclaimWithinCohort` 改为 `Any`，观察份额回收。用 `kubectl patch --type=merge --patch-file`，不是 `kubectl apply`；重新应用 step4 队列会恢复其无抢占配置。
- `step5/priorities.yaml`、`priority-queue.yaml`、`low-job.yaml`、`high-job.yaml` — 同一独立 8 卡队列内，先启动优先级 10 的普通任务，再提交优先级 100 的紧急任务，观察 `withinClusterQueue: LowerPriority`。切换前退出旧甲乙任务并移除旧队列与 Cohort，保留 ResourceFlavor。
- `step6/scattered-small.yaml`、`four-gpu-pod.yaml` — 用 DaemonSet 在每台 worker 放一个单卡 Pod，再提交同机需 4 卡的 Pod，观察总空闲 12 卡仍无法调度。此步绕过 Kueue，聚焦物理节点资源；运行前退出旧实验任务。
- `step6/packed-small.yaml` — 人工集中放置对照：Deployment 的 4 个单卡副本经 nodeSelector 固定到 robot-train-worker；不是自动装箱策略。为保留原 Pending Pod，可先等新 Deployment 有 3 个 Ready，再删除 scattered DaemonSet，观察第 4 个小 Pod 和原 4 卡 Pod 都启动。
- `step6/scheduler-config.yaml`、`scheduler.yaml`、`auto-small.yaml` — 原生 kube-scheduler 的独立 MostAllocated 实验，调度器名 l08-binpack。将组件配置创建成 kube-system/l08-binpack-config ConfigMap，再部署 scheduler.yaml；auto-small 从 1 逐个扩到 4，验证无 nodeSelector 时自动集中。实验只启用 NodeResourcesFit 评分以隔离其他评分因素；默认过滤阶段保留。

## 常用命令
```bash
kind create cluster --config robot-k8s-lab/kind-cluster.yaml   # 建集群
bash robot-k8s-lab/fake-gpu.sh                                  # 上报模拟 GPU
python3 robot-k8s-lab/show_jobs.py                              # 看各训练任务状态
kubectl delete pods -l lab=l08                                  # 清掉实验 Pod
kind delete cluster --name robot-train                          # 用完删掉，释放资源
```
