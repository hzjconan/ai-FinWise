# L08 · k8s 训练调度实战：gang / 配额 / 抢占 / 碎片（机器人数据面试 · 第二阶段专题 D）

> 来源：2026-10 面试插课第二阶段。第一阶段速览见 `L07-robot-video-data-flywheel.md`（第 5 步 + 追问）、速查见 `robot-data-reference.md` 第 6 节。边学边写：每讲完一步追加一节。
> 定位：在本地 kind 集群上**亲手复现**第一阶段讲过的调度问题，并用 Kueue 解决；面试时能说"我实际跑过"。
> 环境：`robot-k8s-lab/`（kind 1 控制面 + 4 worker，每台模拟 4 张 GPU，共 16 张）。GPU 是模拟的：调度 / 计数是真的，没有真实设备。
> 约定：扩容按"机器可加但花钱"；成本 / 性能优化以视频质量不变为前提。
> 状态：已完成（2026-11-01）。下文保留边学边记录的过程，历史段落中的“待回答 / 未运行”以各节后续验证及结尾收尾记录为准。

## 本课目标

- 亲眼看到默认调度器的**部分分配**问题
- 用 Kueue 实现**整体放行**（gang 效果）、**团队配额与借用**、**优先级抢占**
- 理解碎片的成因，以及**装箱调度**（MostAllocated）怎么缓解
- 把实验结论变成面试话术

## 步骤目录

| 步 | 内容 | 状态 |
|---|---|---|
| 1 | 实验环境：kind 多节点集群 + 模拟 GPU | ✅ |
| 2 | 默认调度器复现"部分分配" | ✅ |
| 3 | 装 Kueue：ResourceFlavor / ClusterQueue / LocalQueue，整体放行 | ✅ |
| 4 | 团队配额与借用（cohort） | ✅ |
| 5 | 优先级与抢占 | ✅ |
| 6 | 碎片与装箱调度 | ✅ |
| 7 | 收尾：面试题 + 追加参考文档 | ✅ |

---

## 第 1 步 · 实验环境：kind 多节点集群 + 模拟 GPU

> 🔁 **回顾**（L07 第 5 步）：device plugin 让 k8s 认识 GPU，`nvidia.com/gpu: 4` 申请 4 张；分布式训练要 gang scheduling。

- **kind**（Kubernetes in Docker）：每个"节点"是一个 Docker 容器，一台 Mac 起多节点集群。1 控制面 + 4 worker × 4 卡 = 16 张（"8 台 × 4 卡"缩小版，每台卡数不变）。
- **模拟 GPU**：`nvidia.com/gpu` 只是**扩展资源**（可计数的名字）。真实集群由 device plugin 上报，这里直接 PATCH 节点 `status.capacity`。调度 / 计数是真的，容器里没有 GPU。能练调度、配额、抢占、碎片；练不了 NVLink、MIG、真实吞吐。
- JSON Patch 路径里 `/` 是层级分隔符，资源名自带的 `/` 要转义成 `~1`：`nvidia.com~1gpu`。
- **capacity vs allocatable**：capacity = 总量（脚本 / device plugin 写）；**allocatable** = 扣除系统预留后能分给 Pod 的量，**调度器看它**，由 kubelet 在下次上报节点状态时算出 → 刚 PATCH 完几秒内是 `<none>`（脚本已加等待）。

```bash
kind create cluster --config robot-k8s-lab/kind-cluster.yaml
bash robot-k8s-lab/fake-gpu.sh
```

### 💬 课堂问答

> 🙋 **问**：控制面节点的 GPU 列显示什么？为什么脚本跳过它、为什么不该把训练任务调度到控制面？\
> 🧑 **我的回答**：控制面节点是用来管理k8s集群的，本身不应该跑负载\
> 🤖 **点评**：✅ 对。显示 `<none>`（没有这项资源，不是 0）。➕ 说得更具体：控制面上跑的是 **kube-apiserver、etcd（集群的全部状态数据）、kube-scheduler、kube-controller-manager**。训练任务把 CPU / 内存 / 磁盘 I/O 吃满 → apiserver、etcd 变慢甚至挂掉 → **整个集群**都无法调度、无法提交任务，影响面是全公司。\
> ➕ kind 已经给控制面打了污点 `node-role.kubernetes.io/control-plane:NoSchedule`，普通 Pod 不会被调度上去。➕ **反方向也要防**：真实集群常给 GPU 节点打污点（如 `nvidia.com/gpu=present:NoSchedule`），只有声明了容忍（toleration）的 GPU 任务才能上去，避免普通小服务占用昂贵的 GPU 机器的 CPU 和内存——这就是"节点池"。

### 📌 要记住的（第 1 步）
> kind 在本机起多节点集群；GPU 在 k8s 眼里只是**扩展资源**，PATCH capacity 就能模拟（调度真、设备假）。调度器看 **allocatable** 不是 capacity。控制面跑 apiserver / etcd / scheduler，**不能跑负载**（污点隔离）；GPU 节点也用污点 + 容忍只放 GPU 任务。

---

## 第 2 步 · 默认调度器复现"部分分配"

> 🔁 **回顾**（L07 第 5 步）：默认调度器逐个 Pod 调度；分布式训练要 N 个 worker 同时到齐；两任务各拿一部分 → 部分分配死锁。

**实验**：A、B 各需 3 个 worker，每个 worker 独占整机 4 卡（`nvidia.com/gpu: 4`）→ 各需 12 张、共 24 张 > 集群 16 张；worker **交替提交**（A0 B0 A1 B1 A2 B2）模拟同时到达；容器用 `pause`（只占资源不干活 = "已启动、在等同伴"）。

```bash
bash robot-k8s-lab/step2/submit-interleaved.sh
python3 robot-k8s-lab/show_jobs.py
```

**结果**：
```
任务  需要 运行 等待 占用GPU  状态
a      3    2    1     8   ⚠️ 没到齐，已启动的 worker 占着卡干等
b      3    2    1     8   ⚠️ 没到齐，已启动的 worker 占着卡干等
→ 16 张全部分配、0 张在训练
```
- 原因：默认调度器只看**眼前这一个 Pod**，有机器放得下就放，不知道 A0 / A1 / A2 是"一伙的"。4 个 worker 放满 4 台机器后，A2、B2 永远 Pending，空位被**对方**占着。

### 💬 课堂问答

> 🙋 **问**：先预测 A、B 各有几个 worker 能跑、16 张卡什么状态，再运行对照。\
> 🧑 **我的回答**：预测：提交完后只有A0能跑起来，其他要等GPU释放，16张卡里有12张在干活，另外4张干等\
> 🤖 **点评**：⚠️ 实际是 **4 个 worker 都跑起来（A0、A1、B0、B1），16 张全分配、0 张在训练**，A、B 都到不齐。预测里"只有 A0 跑"与"12 张在干活"也自相矛盾。"等 3 个都能放下才启动"正是 **gang scheduling** 的行为——默认调度器恰恰不会这样做（第 3 步用 Kueue 实现）。

> 🙋 **问**：这个状态会自己恢复吗？要等什么才能打破？\
> 🧑 **我的回答**：不会自己恢复，要手动删掉一个任务的 Pod 才行\
> 🤖 **点评**：✅ 对。➕ 真实集群里能打破它的"外力"还有：**训练框架的等待超时**（如 torchrun 等同伴的 rendezvous 超时）让 worker 报错退出、任务的 `activeDeadlineSeconds` 到期、被更高优先级任务**抢占**。⚠️ 但超时退出后任务**自动重试**，两边又交替提交 → 可能**再次卡死**，反复循环（活锁），期间卡一直在空转。⚠️ 靠人发现也很晚：16 张卡 × 卡住的时长 = 白烧的钱。→ **根本解法是别让它发生**：worker 凑不齐就**一个都不放行**（准入控制 / gang），下一步用 Kueue 做。

### 📌 要记住的（第 2 步）
> 默认调度器逐个 Pod 放置、不认"一伙"，两个多 worker 任务同时到达 → **各占一部分、都到不齐、卡全分配零计算**，不会自愈。外力（人工删除、rendezvous 超时、deadline、抢占）能打破，但重试可能再次卡死。根治靠**准入控制**：凑齐才放行。

---

## 第 3 步 · Kueue 安装、整体准入与组件职责

### 2026-10-30 续课检查

- `kind-robot-train` 的 5 个节点均 Ready，4 个 worker 各有 4 张模拟 GPU，共 16 张。
- Kueue 的 ResourceFlavor、ClusterQueue、LocalQueue CRD 已存在，当前 API 为 `v1beta2`；后续实验配置须按已安装版本核对字段。
- 控制器镜像为 `registry.k8s.io/kueue/kueue:v0.20.2`。Pod 已分配到 `robot-train-worker3`，但处于 `ImagePullBackOff`，控制器尚未启动。
- 宿主机尝试 `docker pull registry.k8s.io/kueue/kueue:v0.20.2`，多数层已缓存，最后一层仍在等待；**尚未完成修复和可用性验证**。

### 本次修复进展

- Docker 两条官方拉取路径均停在约 63 MB 的程序层；改用宿主机 HTTPS 下载 ARM64 镜像清单、配置和所有层，逐项验证 SHA-256，并打包为 OCI archive。
- 使用 `kind load image-archive /tmp/l08-kueue-image/kueue.tar --name robot-train` 导入镜像。
- 将 deployment 的 `imagePullPolicy` 从 `Always` 改为 `IfNotPresent`，新 Pod 已成功启动；随后等待证书初始化与 readiness，通过就绪检查后才算安装完成。临时目录不是仓库的一部分。
- 验证结果：`kubectl rollout status deployment/kueue-controller-manager -n kueue-system` 成功，安装恢复。第 3 步的队列配置与整体准入实验尚未完成。

### 排障先区分环节

- `PodScheduled=True` + `ImagePullBackOff`：已经选好节点，卡在镜像拉取；从镜像地址、凭据、网络等方向查。
- `PodScheduled=False` + `FailedScheduling`：还没选出能运行的节点；查看事件中的资源不足、污点、亲和性等具体原因。
- 当前 deployment 使用 `imagePullPolicy: Always`。如果后续采用宿主机拉取再 `kind load docker-image`，还需处理拉取策略，否则节点仍会请求镜像仓库。

### 课堂问答

> 问：Pod 已经分配到 worker3，但显示 ImagePullBackOff。增加 GPU 节点能解决眼前的问题吗？为什么？\
> 我的回答：这种情况下增加 GPU 完全不能解决问题。\
> 点评：正确。当前阻塞在镜像拉取，新增算力不能修复镜像下载。排障时先看失败发生在哪个环节，再决定是否扩容。宿主机能读取镜像清单，也不代表 Docker 或 kind 节点能够下载完整镜像，各自的网络路径和代理配置可能不同。

安装已恢复，开始讲 ResourceFlavor → ClusterQueue → LocalQueue，再进行整体准入实验；第 3 步暂不标记完成。

### 核心对象（本次教学）

| 对象 | 职责 | 本实验中的例子 |
|---|---|---|
| ResourceFlavor | 描述资源类别，可通过节点标签关联特定硬件 | 一种模拟 GPU；真实集群可区分 A100、H100 |
| ClusterQueue | 集群级配额账本，记录各资源类别的额度和使用情况 | 16 张模拟 GPU 的配额 |
| LocalQueue | 命名空间内提交任务的入口，指向一个 ClusterQueue | 训练任务提交到 `train-queue` |

任务通过 LocalQueue 找到 ClusterQueue，Kueue 按任务整体需求检查和预留配额，然后决定是否准入。ResourceFlavor 描述所用资源的类别。

**边界**：Kueue 的整体准入不等于所有 Pod 原子地同时启动。具体 Pod 到哪台节点仍由 kube-scheduler 决定；只看配额不保证实际放得下，还要考虑单节点容量、碎片、拓扑和其他约束。本实验每个 worker 独占 4 卡、所有 worker 节点相同，便于先观察整体准入。

参考：[Kueue Concepts](https://kueue.sigs.k8s.io/docs/concepts/)。

### 整体准入预测题

> 问：集群配额 16 张 GPU，A、B 各需 3 个 worker × 4 张 GPU。A 先获准运行后，B 会先启动一个 worker 占用剩下 4 张，还是整体排队？\
> 我的回答：B 会等，因为要等到 B 整体能被分配到 12 张 GPU。\
> 点评：正确。在本实验所有训练任务都纳入同一配额管理、没有其他资源约束的前提下，A 预留 12 张后只剩 4 张，不足以准入 B，所以 B 整体排队，不创建训练 worker Pod 抢占余下的卡。对 batch Job 集成，这是通过保持 Job 的 `spec.suspend: true` 实现的。等 A 完成、配额释放，B 才能获准开始。配额够是准入的重要条件，实际 Pod 放置仍受节点容量和其他调度约束影响。

这 4 张剩余配额可用于另一个符合准入条件、需求不超过 4 张的独立小任务，能否越过 B 要看队列策略（后续再讲）；不能先给固定需要 12 张的 B 启动一部分。下一步实操前，先确认本节是否还有疑问。

### 实操 3A：队列已就绪，补全 Job 模板

- 配置路径：`robot-k8s-lab/step3/queues.yaml`。
- 已创建 `l08-fake-gpu` → `l08-gpu-pool`（16 卡）→ `default/train-queue`，ClusterQueue 的 Active 条件已通过。为聚焦整体准入，先使用 StrictFIFO，不启用借用与抢占。
- 模板路径：`robot-k8s-lab/step3/train-job.yaml.tmpl`。普通 batch Job 模拟一组 worker，镜像仍使用 pause；没有真实训练通信，也不会自动完成。
- `completions: 3` 表示 Job 需要成功完成的 Pod 数，`parallelism` 表示允许同时运行的 Pod 数；二者不是同一个含义。Kueue 按该 Job 的并行 Pod 数及每 Pod 的资源请求计算本次准入需求。本练习不启用部分准入或弹性规模。
- 练习：每个 worker 需要 4 卡，任务要求 3 个 worker 同时到齐；`parallelism: __WORKERS__` 应填多少？如果误填为 1，`completions: 3` 能否让 Kueue 按 12 卡准入？
- 当前仅创建队列；Job 模板的预期补全版本做 server dry-run 校验，A/B 尚未实际提交。用户回答后再提交并观察。
- 观察时要查询 Job、Workload 和 Pod。`show_jobs.py` 只看 Pod，看不到尚未创建 Pod 的排队 Job，不能单靠它判断 B 是否存在。

参考：[Kueue 运行 Kubernetes Job](https://kueue.sigs.k8s.io/docs/tasks/run/jobs/)。

### 实操 3B：A 运行，B 整体排队（已验证）

> 练习回答：`__WORKERS__` 应该改成 3。\
> 点评：正确，模板已补为 `parallelism: 3`，准入需求为 3 × 4 = 12 卡。如果填 1，即使 `completions: 3`，也仅按同时运行 1 个 Pod 的 4 卡计算；`completions` 不表示同时启动数。

补全后的 A/B 均通过 server dry-run（API 与 webhook）校验，然后先提交 A，确认 3 个 Pod Ready 后提交 B：

| 观测对象 | A | B |
|---|---|---|
| Job `spec.suspend` | false | true |
| 运行 Pod 数 | 3，分布在 3 台 worker | 0，尚未创建 Pod |
| Workload `Admitted` | True | False |
| 预留 GPU 配额 | 12 | 0 |

B 的 Workload 条件：

```text
QuotaReserved=False reason=WaitingForQuota
insufficient unused quota for nvidia.com/gpu in flavor l08-fake-gpu, 8 more needed
Admitted=False reason=NoReservation
```

复查命令（在仓库根目录执行）：

```bash
kubectl --context kind-robot-train -n default get jobs
kubectl --context kind-robot-train -n default get workloads
kubectl --context kind-robot-train -n default get pods -l lab=l08 -o wide
```

注意：B 是 Job / Workload 排队，并不是已经创建了 3 个 Pending Pod。示例 pause 容器不会自行完成，因此当前保留现场；确认本节无疑问后，再通过删除 A 模拟任务退出释放资源，观察 B 接棒。这不等于演示真实训练成功完成。

> 课堂追问：B 明明需要 12 张卡，错误信息为什么写的是 `8 more needed`？\
> 我的回答：因为有 4 张是空闲的。\
> 点评：正确。本实验总配额 16 张，A 预留 12 张，剩余 4 张，B 需要 12 张，因此缺口为 12 − 4 = 8 张。这里报的是配额缺口；一般情况下，配额余量不等于节点上可用 GPU 的数量，实际是否放得下还需检查节点容量和调度约束。本次观测中，配额余量与空闲 GPU 数一致。

当前停在结果解释环节。确认无疑问后，再释放 A 并观察 B 接棒。

### 追问：GPU limits 与查看排队原因

1. `limits: {nvidia.com/gpu: 4}` 表示该容器固定申请 4 个 GPU 资源单位，不是可按余量分配 1～4 个。GPU 属于扩展资源；只写 limits 时，Kubernetes 自动补上相同的 requests；两者同时写时必须相等。本次直接读取 A 的三个 Pod，均确认 requests=4、limits=4。单个 Pod 的这 4 个资源必须在同一节点满足。分配数量也不等于实际计算利用率，程序可能占着卡但没有计算。
2. 排队原因保存在 B 对应的 **Workload 的 status.conditions** 中。先查名称，再 describe：

```bash
kubectl --context kind-robot-train -n default get workloads
kubectl --context kind-robot-train -n default describe workload job-l08-train-b-00b28
```

在 `Status → Conditions` 中查看 `Type: QuotaReserved` 对应的 Reason 和 Message。当前 Message 包含 `8 more needed`。上述名称是本次现场值，重建 Job 后后缀可能变化；以 get 的输出为准。也可以直接打印所有条件：

```bash
kubectl --context kind-robot-train -n default get workload job-l08-train-b-00b28 \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} reason={.reason} message={.message}{"\n"}{end}'
```

参考：[Kubernetes GPU 调度规则](https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/)。

### 追问：Workload 和 Pod 的关系

本实验中，一个 batch Job 对应一个 Kueue Workload，Job 获准后创建 3 个 worker Pod：

```text
Job：定义任务、并行数、完成数、重试规则
 ├─ Kueue 为其创建 Workload：记录整体资源需求、队列和准入状态
 └─ 获准后由 Job 控制器创建 Pod：实际运行 worker 容器
```

Workload 是 Kueue 的自定义资源，不是普通 Job 必须具备的 Kubernetes 内置对象；它不直接创建 Pod。Kueue 根据 Workload 的准入结果解除 Job 的暂停，Job 控制器才创建 Pod，kube-scheduler 再选节点。这解释了为什么 B 可以已有 Job 和 Workload，但没有 Pod。用户确认本节无疑问。

### 实操 3C：释放 A，B 自动接棒（已验证）

执行：

```bash
kubectl --context kind-robot-train -n default delete job l08-train-a --wait=true --timeout=40s
kubectl --context kind-robot-train -n default wait job/l08-train-b \
  --for=jsonpath='{.spec.suspend}'=false --timeout=40s
kubectl --context kind-robot-train -n default wait pod -l job-name=l08-train-b \
  --for=condition=Ready --timeout=40s
kubectl --context kind-robot-train -n default get jobs,pods,workloads
```

结果：A 的 Job、Pod 和关联 Workload 均已移除；没有修改或重新提交 B，B 自动从 Suspended 变成 Running，3 个 Pod 均为 `1/1 Running`。B 的 Workload 条件变为 `QuotaReserved=True`、`Admitted=True`、`PodsReady=True`，ClusterQueue 当前预留 12 卡。

这里删除 A 模拟任务退出，不代表真实训练成功完成。当前保留 B 运行的现场，尚未进入团队配额与借用实验。

第 3 步结论：固定规模 Job 的资源需求按整体记账；配额不足时整个 Job 排队，不启动一部分 worker；资源释放后 Kueue 自动准入排队任务。具体 Pod 放置仍由 kube-scheduler 完成，配额准入不替代物理容量与拓扑检查。

> 课堂回顾：谁负责把 B 的 `suspend` 改成 `false`，谁负责创建它的 3 个 Pod？\
> 我的回答：都是 Kueue 负责的。\
> 点评：前一半正确，后一半需要区分。Kueue 根据整体配额准入结果把 Job 的 `suspend` 改为 `false`；Kubernetes 的 Job 控制器观察到 Job 解除暂停，按 `parallelism: 3` 创建 Pod；kube-scheduler 为每个 Pod 选择节点；对应节点上的 kubelet 通过容器运行时启动容器。Kueue 决定任务何时获准运行，复用 Kubernetes 原有的执行机制。

```text
Kueue：准入、解除 Job 暂停
  → Job 控制器：创建 3 个 Pod
  → kube-scheduler：为 Pod 选择节点
  → kubelet + 容器运行时：启动容器
```

本节仍停在职责区分的讲解，确认理解且无疑问后再进入下一步。

### 追问：Job 控制器在哪里，和 Kueue 怎么协作？

Job 控制器是 Kubernetes 内置的控制循环，本实验运行在控制面 `kube-system/kube-controller-manager-robot-train-control-plane` 中，并不是需要额外部署的 `job-controller` Pod。Kueue 是另外部署的组件，运行在 `kueue-system`。

两者通过 API Server 中的同一个 Job 对象协作：Kueue 更新 Job 的 `spec.suspend`；Job 控制器观察 Job 状态及已有 Pod，发现解除暂停且 Pod 数不足，再通过 API 创建 Pod。图中的箭头表示资源状态驱动的协作，不表示 Kueue 直接调用 Job 控制器。

可直接查看本次现场的证据：

```bash
kubectl --context kind-robot-train -n kube-system get pods -l component=kube-controller-manager
kubectl --context kind-robot-train -n default describe job l08-train-b
```

Job 的 Events 中实际记录：

```text
From                        Reason            Message
batch/job-kueue-controller   CreatedWorkload   Created Workload: default/job-l08-train-b-00b28
batch/job-kueue-controller   Started           Admitted by clusterQueue l08-gpu-pool
job-controller              SuccessfulCreate  Created pod: l08-train-b-wkzmv
job-controller              SuccessfulCreate  Created pod: l08-train-b-z5mql
job-controller              SuccessfulCreate  Created pod: l08-train-b-fm45g
```

`batch/job-kueue-controller` 是 Kueue 中对接 batch Job 的控制器；`job-controller` 是 Kubernetes 内置 Job 控制器。Pod 的 `metadata.ownerReferences` 也确认它们归属于 `Job/l08-train-b`。Events 会过期，上述为本次课堂记录。

参考：[Kubernetes 控制器](https://kubernetes.io/docs/concepts/architecture/controller/)。

### 追问：Kueue 怎样找到 B，何时触发 reconcile？

是 Kubernetes 控制器常用的 watch + 工作队列 + reconcile 模式，但 Kueue 自己运行控制器逻辑，并不是 kube-controller-manager 自动替 Kueue 执行准入判断。

1. 提交的 Job 带 `kueue.x-k8s.io/queue-name: train-queue` 标签，Kueue 的 batch Job 集成识别并管理它，创建对应 Workload。
2. Workload 通过 `metadata.ownerReferences` 关联原 Job。本次实查 B 的引用为 `apiVersion: batch/v1`、`kind: Job`、`name: l08-train-b`、以及对应 UID。由此能定位具体 Job，不靠解析名称后缀猜测。
3. A 退出，其 Workload 的配额占用被移除；Kueue 更新内部配额状态，重新考虑等待任务，发现 B 可以准入，更新 B 的 Workload 准入状态。本次实查 admission 中为 `clusterQueue: l08-gpu-pool`、`count: 3`、GPU resourceUsage 为 12。
4. Workload 变化触发 Kueue 对关联 Job 的后续协调，Job 集成读取当前准入状态并解除 B 的暂停。Job 的修改随后触发 Kubernetes 内置 Job 控制器协调，创建 Pod。

API Server 提供资源存储和 watch 通知；各控制器注册自己关注的对象及处理逻辑。通知通常使相关对象进入控制器工作队列，reconcile 再读状态并采取必要动作，不是资源变化时 API Server 直接执行业务回调。流程是异步、最终一致的，也可能重试；重复协调不应重复创建一套任务。

参考：[当前版本 Job 协调逻辑](https://github.com/kubernetes-sigs/kueue/blob/v0.20.2/pkg/controller/jobframework/reconciler.go)、[Kueue 准入流程](https://kueue.sigs.k8s.io/docs/concepts/admission/)。

### 补充：Job 模板与程序镜像

- `train-job.yaml.tmpl` 是本地文件；提交后得到 API Server 中的 Job 对象。Job 自带 `spec.template`（Pod 模板），Job 控制器按它创建 Pod，并通过 Pod 的 ownerReferences 关联回 Job。Kueue 改的是集群中 Job 的状态，不会改本地文件。
- 原生 Job 无需 Kueue 就能执行程序。受 Kueue 管理时，整体准入由 Kueue 负责；Pod 创建、节点调度和容器启动分别交给 Kubernetes 原有组件。准入后 Kueue 仍跟踪任务与配额，并可按策略驱逐任务。
- 自己的程序通常通过 Dockerfile 打包为含代码和依赖的镜像，推送到镜像仓库，再填写 `containers[].image`。镜像定义默认启动命令，Job 可用 `command` / `args` 覆盖；路径指容器内部路径。kind 也可以直接导入本地镜像。
- 用户确认上述职责与镜像扩展问题无疑问，继续第 4 步。

---

## 第 4 步 · 团队配额与借用

### 为什么要分团队配额？

第 3 步只有一个 16 卡的 ClusterQueue，不能表达不同团队各自的资源份额。本步考虑：同一物理集群仍为 16 卡，团队甲、乙各一个 ClusterQueue，各有 `nominalQuota: 8`，各有 LocalQueue 作为提交入口。

- 不共享配额时：甲的 12 卡固定规模任务超过自身 8 卡额度，即便乙完全空闲，也无法准入。
- 加入同一 Cohort 并允许借出 / 借入时：甲可以用自身 8 卡加借来的 4 卡运行任务，提高闲置资源利用率。
- `nominalQuota` 表示本团队名义份额；`borrowingLimit` 表示最多可以额外借多少（不是总使用上限）；`lendingLimit` 表示名义份额中最多允许借出多少。
- 借用不增加物理 GPU，也不表示乙之后一来任务就能立即收回。是否可以驱逐借用方，要看回收 / 抢占策略；本步先不启用抢占，后续再讨论回收。
- 为避免与仍在运行的第 3 步 B 混淆，本步使用“团队甲 / 乙”称呼，团队名与任务名是不同维度。当前尚未更改集群配置。

预测题：两团队各有 8 卡名义份额，共享同一 Cohort；乙当前无任务且允许借出至少 4 卡，甲的 `borrowingLimit: 4`。甲提交一个 12 卡任务，在实际节点足够且无其他准入限制时，能否准入？自己的份额和借用部分分别是多少？如果把甲的 borrowingLimit 改为 2 呢？

参考：[Kueue Cohort](https://kueue.sigs.k8s.io/docs/concepts/cohort/)。

### 课堂问答：借用额度预测

> 我的回答：甲能运行，12 张卡里 8 个是自己的，4 个是乙借出的。borrowingLimit 改成 2 不能运行，因为就算借到了也还是比 12 小。\
> 点评：两项都正确。在题设乙有足够可借份额、节点能放下且无其他限制时，甲使用自身名义份额 8 张，并借入 4 张；borrowingLimit 改为 2 后，最多使用 8 + 2 = 10 张，不能准入固定需要 12 张的任务，也不会先启动一部分 worker。borrowingLimit 是额外借入上限，不是总使用上限；实际能借多少仍受共享组可用配额及出借限制约束。

借用是配额记账，不是把某几张物理 GPU 固定归给团队再搬给另一个团队；两个队列可使用相同 GPU 节点池。当前仍未更改集群配置，确认本节无疑问后再做借用实操。

### 追问：ClusterQueue 是什么？

ClusterQueue 是 Kueue 的集群级自定义资源对象，可以理解为一份“资源配额和排队规则的配置 + 当前使用账本”。它没有 namespace；名称中的 Cluster 表示作用域，不代表必须把整个集群的额度都放进去。一个集群可有多个 ClusterQueue，常按团队划分，也可按业务或资源用途划分。

- spec 定义资源类别、名义额度、借入 / 借出限制、排队和抢占等规则；status 记录预留量、使用量、等待任务等状态。
- ClusterQueue 是配置对象，真正读取它、计算能否准入的是 Kueue 控制器与调度逻辑；对象自身不是一个运行程序。
- LocalQueue 是 namespace 内的提交入口，引用某个 ClusterQueue；多个 LocalQueue 可指向同一 ClusterQueue，共用它的额度，不会每个都获得一份独立额度。
- Job 通过队列标签选择 LocalQueue；对应 Workload 进入这条配额与准入管理链路。ClusterQueue 既可管 GPU，也可管 CPU、内存等。
- ClusterQueue 的名义额度由管理员配置，不会自动创造或锁定同数量的物理 GPU。ResourceFlavor 可通过节点标签关联硬件类别，实际 Pod 放置仍需物理资源可用。

本次已运行的配置位于 `robot-k8s-lab/step3/queues.yaml`：`default/train-queue` 指向 `l08-gpu-pool`，后者为 `l08-fake-gpu` 类别配置 16 张 GPU。之前 A、B 都提交到这个入口，合计受同一个 16 卡账本约束。下一步团队借用实验才会改成两个独立的 8 卡账本，并加入共享组；当前未修改。

```text
default 中的 Job → default/train-queue（LocalQueue）
                → l08-gpu-pool（ClusterQueue：16 卡额度与排队规则）
```

检查问题：如果甲乙各有 LocalQueue，但两个 LocalQueue 都指向同一个 16 卡 ClusterQueue，是否已经实现“甲乙各有 8 卡份额”？（待回答）

用户回答“不一定，集群里的 16 卡有可能都已经被占了”。需要分清：当前物理卡是否空闲，与配置是否定义团队份额，是两件事。即使全部空闲，两个 LocalQueue 指向同一个 16 卡 ClusterQueue 也不会自动分成各 8 卡。用户希望先对照现有文件理解，暂不进入借用实操。

代码对照：`step3/queues.yaml` 的 `kind: ClusterQueue` 对象名为 `l08-gpu-pool`，GPU 的 `nominalQuota: 16` 定义其额度；同文件的 `kind: LocalQueue` 对象名为 `train-queue`，通过 `spec.clusterQueue: l08-gpu-pool` 引用前者。`step3/train-job.yaml.tmpl` 在 Job 标签中写 `kueue.x-k8s.io/queue-name: train-queue`，引用的是同 namespace 的 LocalQueue。三个名称串成：Job → train-queue → l08-gpu-pool。当前只有一份共享的 16 卡额度，还没有团队甲乙的独立队列配置。

参考：[Kueue ClusterQueue](https://kueue.sigs.k8s.io/docs/concepts/cluster_queue/)。

### 教学约定更新

用户确认 Job → LocalQueue → ClusterQueue 的关联已清楚，并要求：后续新增或修改 YAML / 其他代码时，即使由 agent 代写，也要带用户过一遍，重点讲与本课有关的字段；解释后再进入运行和观察，不跳过配置阅读。

### 实操 4A：先读共享队列配置（尚未应用）

新增 `robot-k8s-lab/step4/queues.yaml`，已通过 server dry-run 校验（含 Cohort、2 个 ClusterQueue、2 个 LocalQueue），当前没有切换集群。团队甲对应 team-a，团队乙对应 team-b；区别于上一步已删除的任务 A 和仍运行的任务 B。

配置关联：

```text
甲的 Job → team-a-queue → l08-team-a（名义 8，最多借入 4）┐
                                                      ├→ l08-teams Cohort
乙的 Job → team-b-queue → l08-team-b（名义 8，最多借入 4）┘
```

逐项阅读要点：

- `kind: Cohort` / `name: l08-teams`：定义共享组，不配置额外资源额度，本实验总名义额度仍为两个队列的 8 + 8 = 16。
- 两个 ClusterQueue 的 `cohortName: l08-teams`：把它们加入同一共享组。
- `namespaceSelector` 允许 default namespace 的任务使用；本实验两队都用 default，只练配额，不演示权限隔离。
- 两队使用同一个 `l08-fake-gpu` flavor 与 `nvidia.com/gpu` 资源，因而可以在同一资源类别上共享额度。
- 每队 `nominalQuota: 8`、`borrowingLimit: 4`、`lendingLimit: 4`：自身名义份额 8，最多额外借入 4，最多借出自身空闲份额中的 4；实际借用量还受共享组余量约束。
- `preemption.reclaimWithinCohort: Never`、`withinClusterQueue: Never`：先禁用这两类抢占，借出的份额不会因为原团队来任务就自动驱逐借用方。本步先观察借用和排队，下一步再讲抢占。
- 两个 LocalQueue 的 `spec.clusterQueue` 各指向本团队 ClusterQueue。后续 Job 的队列标签必须选择相应 LocalQueue，才能计入对应团队的账本。
- 运行前需退出旧任务 B、移除旧 LocalQueue / 16 卡 ClusterQueue，但保留共用的 ResourceFlavor；不能在同一批 16 卡物理资源上同时使用旧 16 卡额度和新 8 + 8 额度，以免重复记账。此清理尚未执行。

> 检查问题：甲的 Job 标签应填写 `team-a-queue`、`l08-team-a` 还是 `l08-teams`？\
> 我的回答：应该是 l08-team，因为甲和乙现在需要通过 Cohort 绑在一起。\
> 点评：共享组的理解对，但引用层级混淆了。Job 的 `kueue.x-k8s.io/queue-name` 填 LocalQueue 名 `team-a-queue`；LocalQueue 的 `spec.clusterQueue` 填 ClusterQueue 名 `l08-team-a`；ClusterQueue 的 `spec.cohortName` 才填 `l08-teams`。Job 不直接指定 Cohort。

> 追问：乙的 Job 的队列标签应填什么？\
> 我的回答：team-b-queue。\
> 点评：正确。乙的关联路径为 Job → `team-b-queue` → `l08-team-b` → `l08-teams`。当前等待确认本段配置是否还有疑问，尚未应用 step4 配置。

### 实操 4B：甲借入 4 卡（已验证）

用户确认无疑问后，新增 `step4/team-a-job.yaml` 并讲解：队列标签改为 `team-a-queue`，Job 名为 `l08-team-a-train`；`parallelism: 3`、`completions: 3`、每 Pod 4 卡、`suspend: true` 沿用之前的固定规模设置。借用数量不写在 Job 内，由 Kueue 按该队列的名义份额和借用规则计算。镜像仍为 pause，只模拟占卡，不会自行完成。

服务端 dry-run 校验共享队列与 Job 均通过。随后退出旧任务 B，等待其 Pod 移除，删除旧 `train-queue` 和 `l08-gpu-pool`；保留共用 ResourceFlavor。应用 step4 队列，两个 ClusterQueue 的 Active 条件通过后提交甲的任务。

观察命令：

```bash
kubectl --context kind-robot-train -n default get jobs,pods,workloads
kubectl --context kind-robot-train get clusterqueue l08-team-a -o yaml
```

第一条确认 Job Running、3 个 Pod 均为 `1/1 Running`、Workload 的 ADMITTED=True。第二条查看 `status.flavorsReservation`（预留配额）及 `status.flavorsUsage`（已准入用量），本次两者均包含：

```yaml
name: l08-fake-gpu
resources:
  - name: nvidia.com/gpu
    total: "12"
    borrowed: "4"
```

`total: 12` 包含借入的 4 张，不能再加一次；这也不是 GPU 实际计算利用率。甲自身名义份额 8，加借入 4，共 12。乙的 total 和 borrowed 均为 0，表示乙当前没有预留或运行任务，出借份额不记为乙的任务用量。

当前只运行甲的 12 卡任务，保留该现场；团队乙尚未提交任务。确认配置和结果无疑问后，再验证“乙来了任务，是否能立即收回借出份额”。

### 实操 4C：乙有名义份额，仍需等待回收（已验证）

新增并先讲解 `step4/team-b-job.yaml`：队列标签为 `team-b-queue`，`parallelism: 2`、`completions: 2`，每个 Pod 仍需 4 卡，共 8 卡；`suspend: true` 等 Kueue 放行，镜像仍为 pause。配置通过 server dry-run 后提交。

观测结果：甲的 3 个 Pod 继续 Running，甲的 ClusterQueue 仍为 total=12、borrowed=4；乙的 Job 为 Suspended，没有创建 Pod，乙的 Workload 为 `QuotaReserved=False`、`Admitted=False`，原因是 `insufficient unused quota ... 4 more needed`。

```bash
kubectl --context kind-robot-train -n default get jobs,pods,workloads
kubectl --context kind-robot-train -n default describe workload job-l08-team-b-train-1fe5d
kubectl --context kind-robot-train get clusterqueue l08-team-a -o yaml
```

Workload 后缀以当前 get 输出为准。乙名义份额 8 不代表其所需额度在任何时刻都立即可用。甲已用 12，16 卡共享组只剩 4；乙的固定规模任务需 8，缺口 4。当前 `reclaimWithinCohort: Never`，不会为乙驱逐甲，甲也不支持在本实验中自动从 12 缩到 8，所以乙整体等待。

这是第 4 步的重要边界：借用改善闲置利用率；要使份额拥有者需要资源时可主动回收，还需配置合适的回收 / 抢占策略，并考虑被驱逐任务的恢复成本。当前保留甲运行、乙排队的现场，不启用抢占，等待本节问题确认后再进入第 5 步。

课堂回顾（待回答）：乙明明有 8 卡名义份额，为何现在不能立即启动？怎样从当前配置中判断是否允许回收借出的份额？

用户确认第 4 步无疑问，进入第 5 步。

---

## 第 5 步 · 回收与优先级抢占

### 5A：先区分两种动机，再阅读拟修改字段

- **份额回收**：乙申请自身 8 卡名义份额，但甲的队列用到 12 卡，超过甲的 8 卡名义份额；可以按策略驱逐借用方任务，为乙腾出资源。
- **优先级抢占**：更重要的任务按策略驱逐低优先级任务。与份额回收相关但不是同一概念；回收可以配置成不比较双方优先级。

本次先演示份额回收，尚未改配置。拟在乙的 ClusterQueue `l08-team-b` 设置：

```yaml
spec:
  preemption:
    reclaimWithinCohort: Any
    withinClusterQueue: Never
```

`reclaimWithinCohort` 写在**请求回收一方（乙）**的队列上，表示该队列的等待任务可以按策略驱逐同 Cohort 中超出自身名义份额的队列任务。当前经典抢占策略下，乙的任务须能落在乙自己的名义份额内。`Any` 不要求乙的任务优先级更高；`LowerPriority` 则只允许驱逐较低优先级任务；`Never` 禁用此类回收。`withinClusterQueue: Never` 继续禁用队列内部抢占。

**Any 并非任意抢别人保底份额**，仍受同共享组、对方队列处于借用状态等条件限制。本实验甲乙目前任务优先级相同，选择 Any 是为了先观察不依赖优先级的份额回收，之后再单独学习优先级。

本实验使用固定规模 batch Job，抢占单位是整体 Workload：不会只删除甲一个 4 卡 Pod 并让其余两个继续训练。甲会整体暂停、三个 Pod 被移除，原 Job 保留等待再次准入；乙获得 8 卡后甲需要的 12 卡仍放不下。Kueue 不会替训练程序保存 checkpoint；真实训练要另行实现持久化和恢复。本实验是 pause 容器，不验证训练进度恢复。

预测题（待回答）：启用乙的回收策略后，甲会从 3 个 worker 自动缩成 2 个继续运行，还是整体暂停？乙启动后，甲能否立刻重新运行？

参考：[Kueue 抢占](https://kueue.sigs.k8s.io/docs/concepts/preemption/)。

### 5B：乙回收份额，甲整体暂停（已验证）

> 预测回答：1. 甲会暂停。2. 不能，借不到足够的 GPU。\
> 点评：正确。乙占 8 后共享组剩 8，甲固定需要 12，不能再次准入。

新增并先讲解 `step5/reclaim-team-b.yaml`：这是只有 `spec.preemption.reclaimWithinCohort: Any` 的 merge patch。它没有 kind / metadata，目标由命令中的 `clusterqueue l08-team-b` 指定；只改变乙的回收权限。原 step4 YAML 保留为无抢占基线，重新 apply 它会恢复 Never。

先使用 `--dry-run=server` 校验补丁，通过后执行：

```bash
kubectl --context kind-robot-train patch clusterqueue l08-team-b \
  --type=merge --patch-file robot-k8s-lab/step5/reclaim-team-b.yaml
kubectl --context kind-robot-train -n default get jobs,pods,workloads
kubectl --context kind-robot-train -n default describe workload job-l08-team-a-train-83449
```

观测：甲的 Job 保留但转为 Suspended，原来的三个 Pod 均被移除；乙自动转为 Running，两个 Pod 均为 `1/1 Running`。甲的 Workload 为 `Admitted=False`，并记录：

```text
Evicted=True reason=Preempted
Preempted=True reason=InCohortReclamation
Requeued=True reason=Preempted
QuotaReserved=False reason=WaitingForQuota
... insufficient unused quota ... 4 more needed
```

事件中双方 effective priority 均为 0，证明本次是在 Any 策略下回收份额，而非高优先级驱逐低优先级。当前甲整体排队、乙运行；未修改优先级、未演示 checkpoint 恢复。下一段讲优先级前先确认当前配置与结果无疑问。

### 5C：任务优先级与抢占权限（配置阅读，尚未运行）

用户确认份额回收无疑问。新增 `step5/priorities.yaml`，定义两种 Kueue WorkloadPriorityClass：`l08-experiment` 的 value 为 10，`l08-production` 为 100。已通过 server dry-run，尚未应用，现场仍为甲排队、乙运行。

阅读要点：`value` 与 metadata 同级，不在 spec 下；值越大表示任务优先级越高，100 不表示 GPU 数量或百分比。Job 在自己的 metadata.labels 中用 `kueue.x-k8s.io/priority-class: l08-production` 引用该对象。`queue-name` 决定使用哪个账本，`priority-class` 决定该任务的 Kueue 优先级，是两个独立标签。

WorkloadPriorityClass 管 Kueue 整体任务的排队和抢占，不改变 Pod 的优先级；Kubernetes 的 PriorityClass / Pod priorityClassName 是另一层机制。此处暂不同时引入 Pod 优先级，避免把 Kueue Workload 驱逐与 kube-scheduler 的 Pod 抢占混淆。

“任务更重要”不等于“允许抢占”：策略仍为 Never 时，高优先级也不能靠抢占踢掉已运行任务。`reclaimWithinCohort: LowerPriority` 限制跨队列份额回收仅针对较低优先级任务，其他回收条件仍须满足；`withinClusterQueue: LowerPriority` 则允许同一 ClusterQueue 内按规则驱逐较低优先级任务。下一实验拟先用同一队列的普通 / 紧急任务，单独观察优先级抢占，运行前会另行讲解配置变更。

预测题（待回答）：在同一队列中，普通任务优先级 10，紧急任务优先级 100，且配额不足以同时准入二者。若 `withinClusterQueue: Never`，紧急任务能否仅凭较高优先级抢占正在运行的普通任务？改为 LowerPriority 后是否才允许考虑这种抢占？

参考：[Kueue WorkloadPriority 用法](https://kueue.sigs.k8s.io/docs/tasks/manage/run_job_with_workload_priority/)。

> 预测题回答：不会。\
> 点评：正确。`withinClusterQueue: Never` 禁止队列内抢占，紧急任务不能仅凭更高优先级驱逐正在运行的普通任务。优先级表达任务的重要程度，抢占策略决定是否允许中断其他任务。改为 `LowerPriority` 后才允许考虑驱逐同队列中的较低优先级任务；最终仍需满足资源等准入条件。当前优先级配置尚未应用，确认本节无疑问后再进入实操。

### 5D：同队列优先级抢占（已验证）

用户确认无疑问。为单独观察优先级，新增并先讲解 `step5/priority-queue.yaml`：独立 ClusterQueue `l08-priority-pool` 配额 8，不加入 Cohort；LocalQueue 为 `priority-queue`；`withinClusterQueue: LowerPriority`，`reclaimWithinCohort: Never`。物理集群仍为 16 卡，本实验只开放 8 卡配额，多余物理空闲卡不会自动增加队列额度。

新增并先讲解 `step5/low-job.yaml` 和 `high-job.yaml`：两者都进入 `priority-queue`，均 parallelism=2、每 Pod 4 卡，共需 8 卡；Job 上的 `kueue.x-k8s.io/priority-class` 分别引用 `l08-experiment`（10）和 `l08-production`（100）。Pod 模板仍用 pause，不验证真实训练进度恢复。

执行顺序：退出并移除旧甲乙任务、两个 LocalQueue / ClusterQueue 及 Cohort，保留 ResourceFlavor；应用优先级定义与新队列；新配置及两个 Job 的 server dry-run 均通过；先提交 low 并等两个 Pod Ready，再提交 high。

结果：普通任务从 Running 转为 Suspended，其两个 Pod 移除；紧急任务自动获准，两个 Pod 均为 `1/1 Running`。普通 Workload 的 priority=10、ADMITTED=False，紧急 Workload 的 priority=100、ADMITTED=True。普通 Workload 记录：

```text
Evicted=True reason=Preempted
Preempted=True reason=InClusterQueue
Requeued=True reason=Preempted
```

事件明确显示抢占方 effective priority=100、被抢占方 effective priority=10，原因是 `prioritization in the ClusterQueue`，与上一实验的 `InCohortReclamation` 不同。

```bash
kubectl --context kind-robot-train -n default get jobs,pods,workloads
kubectl --context kind-robot-train -n default describe workload job-l08-low-train-0b387
```

Workload 名称后缀以 get 结果为准。当前保留 high 运行、low 排队现场；尚未释放 high 或验证 low 再次启动。

> 课堂回顾：真实训练中，普通任务被驱逐后重新获准，Kueue 会自动恢复模型参数和训练步数吗？为了避免从头重训，程序需要具备什么能力？\
> 我的回答：Kueue 本身不具备恢复业务的能力，训练程序需要自己设置 checkpoint。\
> 点评：正确。Kueue 重新准入后由 Kubernetes 创建新的 Pod，业务进度必须由训练程序恢复。完整恢复通常要保存模型参数、优化器状态、训练步数 / 学习率调度状态及必要的数据进度、随机数状态；checkpoint 写入 PVC、对象存储等 Pod 删除后仍可读取的位置，不能只放容器可写层或 emptyDir。程序启动时主动加载最近一份有效 checkpoint。定期保存是基础，可配合优雅终止时保存，但不能只依赖退出信号，节点故障可能没有保存机会。

抢占损失通常包括最近一次有效 checkpoint 之后的重复计算和重新启动 / 加载开销，保存越频繁也会带来更多 I/O 成本。本实验仍只验证 pause 容器的调度行为，没有演示训练状态恢复。确认本节无疑问后，再释放紧急任务、观察普通任务自动重新启动；这只能证明重新运行，不等于恢复业务进度。

### 追问：Pod 被抢占时，如何触发 checkpoint？

采用两道机制：训练中每隔一定步数 / 时间定期保存；正常终止时捕获 SIGTERM，争取补存最近进度。Pod 正常删除的典型流程为 kubelet 让运行时向容器主进程发送终止信号（通常 SIGTERM），在宽限期内等待退出，超时后强制终止。preStop（若配置）也占同一宽限期，不额外获得完整时长。Kueue 不会调用训练程序的 checkpoint 函数。

训练程序可注册 SIGTERM handler，handler 只设置退出标记；在一次完整参数更新后的安全点检查该标记，保存状态后退出。不要在信号回调中直接做复杂 GPU 运算或分布式通信。容器启动命令应让训练进程接收到信号；shell 包装时使用 exec 或正确转发信号。

Pod 模板可设置 `spec.template.spec.terminationGracePeriodSeconds`，例如 120 秒；这是允许优雅退出的时间，不是保存间隔，也不保证 checkpoint 能完成。预算要包含当前训练步耗时、状态落盘及必要上传 / 清理时间；延长宽限期也会延迟资源交接。本节仅讲示意配置，没有修改当前 pause Job。

保存可用 PyTorch 的 torch.save，将模型 / 优化器 state_dict、步数、调度器等组成 checkpoint。写入持久位置，保留上一份完整快照；例如同一支持原子重命名的文件系统内先写临时文件再原子替换，对象存储可用版本化对象和完成标记。新 Pod 启动时加载最近完整版本，再继续训练。

SIGKILL、OOM、节点断电等可能没有可用的退出保存机会，因此定期 checkpoint 是基础，SIGTERM 补存只是降低损失的机会。多 worker 分布式训练还须协调统一安全点和快照步数，FSDP 等分片状态通常需多个 rank 参与，不能直接把单进程的退出保存示意套给各 worker，否则可能出现通信挂住或不一致快照。

参考：[Kubernetes Pod 终止](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination)、[PyTorch 保存与加载](https://docs.pytorch.org/tutorials/beginner/saving_loading_models.html)。

### 追问：checkpoint 要保存的各项内容

部署通常只需模型推理所需权重 / buffer，以及匹配的结构配置、预处理和动作归一化信息；继续训练还需要恢复“下一步怎么更新、读什么数据”。训练 checkpoint 是这些状态在同一个安全点的快照。

| 状态 | 保存内容与原因 | 遗漏的后果 |
|---|---|---|
| 模型 | 参数及持久 buffer，例如 BatchNorm 运行均值 / 方差；PyTorch model.state_dict() 通常包含这些 | 失去学到的结果，或前向行为发生变化 |
| 优化器 | Adam 的一阶 / 二阶梯度滑动统计、step、参数组等；SGD momentum 等 | 权重虽接着用，优化动态重新起步，不能当作原训练的完整延续 |
| 进度与学习率调度 | 已完成 optimizer 更新数 global_step、epoch、scheduler 状态 | warmup / 衰减位置错误、重复训练或错误提前结束 |
| 数据读取 | 数据集版本、shuffle / sampler 状态、消费位置、必要的每 rank 状态 | 重复或跳过样本，训练分布改变；仅 epoch 不足以精确恢复 epoch 中途 |
| 随机数生成器 | Python、NumPy、PyTorch CPU / CUDA 及必要 worker / rank 的 RNG 状态 | Dropout、增强、采样序列变化；只重新设初始 seed 不能恢复到中途状态 |
| 混合精度 | 使用 FP16 GradScaler 时保存其 scale 和更新状态；BF16 常不使用 scaler | 数值稳定性相关状态被重置 |
| 其他算法状态与元信息 | EMA（若使用）、模型 / 训练配置、代码与数据版本、归一化统计、格式版本 | 无法正确重建模型、复现环境或解释结果 |

loss、best_metric 等有助于日志、选最佳模型与早停；有早停器等控制器时也须保存对应状态。并非所有项目每一项都存在，按所用训练组件保存。

通常选完整 optimizer 更新后、梯度已清空的边界保存，此时不用保存梯度和旧计算图。如果在梯度累积中途保存并要求原样续算，还要保存尚未应用的梯度和累积进度，或明确回退到之前完整更新边界。前文“checkpoint 不带梯度”应理解为常见更新边界的做法，不能泛化为任何 checkpoint 都不需要梯度。

数据预取可能使 DataLoader 内部游标超前于实际训练消费位置，精确恢复不能简单记录“读过多少批”；流式数据、多 worker、换 world size 更需专门状态管理。多 rank 状态须对应同一一致性快照；保存 RNG 也不保证跨版本、硬件或非确定性算子逐位相同。checkpoint 不保存完整运行进程、CUDA 上下文或通信连接，新进程需要重建这些运行环境。

用 global_step=5000 的例子：权重应是完成第 5000 次更新后的权重，优化器和调度器也处于匹配阶段，数据从之后应消费的位置继续。元信息中明确 step 表示“已完成更新数”还是“下一步索引”，避免 off-by-one。当前为讲解，没有加入训练代码或修改集群。

> 检查问题：保存了第 5000 步的模型参数，却未保存 Adam 优化器状态，恢复后是“已经学到的结果没了”，还是“结果保留了，但后续更新行为可能改变”？\
> 我的回答：是“结果保留了，但后续更新行为可能改变”。\
> 点评：正确。模型参数承载已学结果，Adam 的一阶 / 二阶历史统计等决定后续更新行为；仅恢复权重仍可继续训练，但不是原过程的完整续接。当前停在 checkpoint 内容讲解，确认无疑问后再回到调度实验。

### 基础补充：Adam 是什么？

Adam（Adaptive Moment Estimation）是一种优化器，即按梯度更新模型参数的算法。训练循环中，前向计算预测，loss 衡量误差，反向传播计算各参数的梯度，优化器再据此修改参数。梯度给出当前位置的局部变化信息，并不直接保证有限步长更新后误差一定下降。

最基本的梯度下降更新可写为“新参数 = 旧参数 − 学习率 × 当前梯度”。例如参数 2、梯度 0.5、学习率 0.1，更新为 1.95；学习率控制步长。

Adam 在当前梯度之外，为每个参数维护一阶矩估计 m（梯度的指数滑动平均）和二阶原始矩估计 v（梯度平方的指数滑动平均），并记录更新计数 t。直观上 m 平滑更新方向，v 对更新尺度作归一化；完整公式还包含偏差修正及避免除零的小常数。它不是保存全部历史梯度，而是保存其压缩统计。不能把 v 严格等同于梯度方差，也不能据此断言 Adam 总比其他优化器更好。

因此，同一模型权重与同一当前梯度，在不同 m、v、t 状态下可能得到不同更新。checkpoint 中模型 state_dict 保存已学结果，optimizer state_dict 保存这些优化器状态及参数组配置。每个参数通常对应 m、v 两份状态，这也是 Adam 带来额外显存和 checkpoint 存储成本的原因之一。

本节只解释优化器基础，不运行新训练代码；用户可继续追问梯度、学习率或滑动平均，再确认是否回到调度实验。

参考：[Adam 原论文](https://arxiv.org/abs/1412.6980)、[PyTorch Adam](https://docs.pytorch.org/docs/main/generated/torch.optim.adam.Adam_class.html)。

### 基础补充：梯度与指数滑动平均

用单参数模型“预测值 = w”、目标为 3、loss=(w−3)² 说明梯度。梯度是 loss 相对参数的局部变化率，本例为 2(w−3)：w=2 时梯度 −2，参数稍增会使 loss 下降；w=4 时梯度 +2，参数稍增会使 loss 上升，应减小参数。简单梯度下降 w_new=w−lr×gradient，lr=0.1 时，2 更新为 2.2，4 更新为 3.8，loss 均从 1 变成 0.64。梯度不是误差本身，也不是“参数必须改成的数”；多参数模型的梯度包含每个参数的偏导数。步长过大可能越过低点，不能保证每次有限步长更新都降低 loss。

Adam 的“滑动平均”具体为指数滑动平均：m_new=β×m_old+(1−β)×g_current，例如 β=0.9 时为旧统计占 90%、新梯度占 10%。假设此前 m=1，新批次梯度突然为 −1，新 m=0.9×1+0.1×(−1)=0.8，不会因单批反向反馈立即完全反向。若后续梯度持续为负，m 会逐渐转负，代价是有响应滞后。把递推展开后，越早的梯度权重衰减越多；这不是只对最近固定 N 次取算术平均，历史权重按指数衰减，存储时只需保留当前统计。Adam 中 v 对梯度平方做同类平均。

本节只讲局部变化率与平滑统计，不引入完整 Adam 更新公式或新代码。检查问题（待回答）：w=2、目标=3、梯度=−2、学习率=0.1 时，更新后参数会变大还是变小？

> 我的回答：会变大。\
> 点评：正确，2 − 0.1 × (−2) = 2.2，减去负数使参数增大，本例更接近目标 3。接下来确认滑动平均：若旧统计为正、当前一批梯度突然为负，平均结果仍可能为正，因为它保留了近期历史的权重。当前尚未返回调度实验。

用户解释滑动平均为“Adam 把最近一次梯度的变化影响变小了”。方向正确，更准确是降低当前一批梯度对统计值的影响、保留此前趋势，而不是直接对“梯度的变化量”做平均。持续负梯度会使一阶统计逐渐转负。

### 数学回顾：导数，以及平方误差中的 2 从哪里来

导数是某一点的瞬时变化率，也是曲线在该点切线的斜率。平均变化率为 `[f(x+h)−f(x)]/h`；让 h 趋近于 0，若极限存在就得到 f'(x)。局部可用 `Δf ≈ f'(x)×Δx` 估计变化，步长越大越不能忽略曲线弯曲带来的误差。

例如 f(x)=x²，在 x=2 处，平均变化率为 `[(2+h)²−4]/h=4+h`，当 h 趋近 0 时为 4，故 f'(2)=4；x 从 2 增加 0.01 时，f 约增加 0.04，实际增加 0.0401。一般位置展开为 `[(x+h)²−x²]/h=2x+h`，因此平方函数导数为 2x。

对于 loss(w)=(w−3)²，令参数增加 h 后展开，差商为 `2(w−3)+h`，因此导数为 2(w−3)。这里的 2 来自平方函数求导，不是 Adam 的固定系数；若定义 loss=½(w−3)²，导数就为 w−3。

导数为正表示局部随输入增大输出增加，为负表示局部随输入增大输出减少；导数为零表示一阶局部变化率为零，不一定是最小值。单参数模型的梯度就是该导数；多参数模型的梯度由每个参数对应的偏导数组成，计算某个偏导时将其他参数保持不变。本节只做简短数学回顾，尚未推进调度实验。

> 检查问题：某个位置的导数是 −2，输入增加很小一点，输出会增加还是减少？\
> 我的回答：减少。\
> 点评：正确，局部近似为 Δ输出 ≈ −2 × Δ输入。例如输入增加 0.01，输出约减少 0.02。对应到训练，若 loss 对参数的导数为负，小幅增大参数有助于降低 loss；这说明为什么梯度下降用“参数减去学习率乘梯度”。确认数学补充无疑问后再返回调度实验。

### 5E：紧急任务退出，普通任务自动重新运行（已验证）

用户确认数学补充无疑问，返回调度实验。本次没有新增或修改实验 YAML，删除紧急 Job 模拟其退出：

```bash
kubectl --context kind-robot-train -n default delete job l08-high-train --wait=true --timeout=40s
kubectl --context kind-robot-train -n default wait job/l08-low-train \
  --for=jsonpath='{.spec.suspend}'=false --timeout=40s
kubectl --context kind-robot-train -n default wait pod -l job-name=l08-low-train \
  --for=condition=Ready --timeout=40s
kubectl --context kind-robot-train -n default get jobs,pods,workloads
```

结果：没有手动修改或重新提交 low，原 Job 和 Workload 保留并重新获准；Job 转回 Running，新建两个 Pod（本次为 `l08-low-train-59mqf`、`l08-low-train-9rljj`），均为 `1/1 Running`，不同于被抢占前的 Pod。Workload 的 QuotaReserved / Admitted / PodsReady 均为 True，Evicted / Preempted 均为 False；队列用量恢复为 8 卡。

本实验闭环：普通任务先运行 → 紧急任务按较高优先级抢占 → 普通任务整体暂停并重排队 → 紧急任务退出 → 普通任务自动新建 Pod 运行。这验证调度层的重新运行，不验证业务训练状态恢复；checkpoint 的保存、持久化与加载须由训练程序负责。

第 5 步已完成。当前仅普通任务运行，保留现场；确认本步无疑问后再进入第 6 步“碎片与装箱调度”。

---

## 第 6 步 · GPU 碎片与装箱调度

用户确认第 5 步无疑问。先讲概念与预测，尚未改变集群；以下是待复现的假设布局，不是当前实测状态。

### 6A：总量够，不代表单个 Pod 放得下

假设 4 台 worker 每台 4 卡，每台各有一个 1 卡小任务：

| 节点 | 已分配 | 空闲 |
|---|---:|---:|
| worker 1 | 1 | 3 |
| worker 2 | 1 | 3 |
| worker 3 | 1 | 3 |
| worker 4 | 1 | 3 |
| 合计 | 4 | 12 |

来了一个单 Pod 申请 4 卡的任务，虽然全局有 12 卡空闲，每个节点却只剩 3 卡，找不到能放下这个 Pod 的节点。这是资源碎片：不能把多台节点的卡拼进同一个普通 Pod。

配额准入与节点放置是两道判断。即便一个只检查总配额的 Kueue 队列还有额度、放行了该 Job，Pod 仍可能因单节点资源不足而 Pending。本步只讨论默认 Pod 放置约束，暂不启用拓扑感知准入或 Pod 就绪超时回收。

如果起初将 4 个单卡小任务集中到同一台 worker，其余 3 台各有完整 4 卡，新的整机任务就能运行。装箱调度的思路是尽量集中使用资源以保留完整空闲节点；后续会讲 NodeResourcesFit 的 MostAllocated 以及 GPU 资源评分配置。它影响新 Pod 的选择，不会自动搬迁已经运行的 Pod，且受其他调度约束和评分影响。

预测题（待回答）：上述每台已用 1 卡、各剩 3 卡的布局，单 Pod 申请 4 卡的任务能否启动？同样 4 个单卡小任务若集中在一台，结果为何不同？

参考：[Kubernetes 资源装箱](https://kubernetes.io/docs/concepts/scheduling-eviction/resource-bin-packing/)。

> 预测题回答：第一种不能，没有单个 worker 能提供 4 个 GPU，一个 Pod 不能为了凑满 4 个 GPU 被分配到多个 worker；第二种可以，因为存在有 4 张空闲 GPU 的单个 worker。\
> 点评：正确。单个 Pod 的资源必须在同一节点满足；两种布局总空闲量相同，但完整可用节点数不同。这是碎片问题，区别于总配额不足，也区别于多 worker 训练的部分准入问题。当前仅完成概念预测，尚未清理第 5 步现场或新增第 6 步实验 YAML；确认无疑问后再带读配置并实际复现。

### 6B：每台占 1 卡，4 卡 Pod 无法放置（已验证）

用户确认无疑问。新增并先讲解两份配置：

- `step6/scattered-small.yaml`：DaemonSet `l08-small-scattered`，每个 Pod 申请 1 张 GPU；nodeAffinity 要求节点没有 `node-role.kubernetes.io/control-plane` 标签，在本集群对应 4 台 worker；selector 与模板标签匹配，让控制器识别自己管理的 Pod。DaemonSet 在每个符合条件的节点维护一个 Pod，刻意构造均匀分散布局，不是证明默认调度器必然如此放置普通任务。
- `step6/four-gpu-pod.yaml`：普通 Pod `l08-four-gpu`，申请 4 张 GPU。两份配置都不进入 Kueue，单独观察 kube-scheduler 的资源过滤；没有使用更高的 Pod 优先级抢占小任务。

服务端初次校验拒绝了直接填写 `preemptionPolicy: Never` 的 Pod（Priority admission 要求与优先级类一致）；移除该字段后，两份配置均通过 server dry-run。正式运行前退出旧 low Job、等待 Pod 移除，删除旧 LocalQueue 和 8 卡 ClusterQueue，保留 ResourceFlavor 与优先级定义。先启动 DaemonSet，确认 4 个 Pod Ready 后提交 4 卡 Pod。

结果：每台 worker 各运行一个 1 卡 Pod，总已分配 4、空闲 12；`l08-four-gpu` 为 Pending，Node 为 `<none>`，`PodScheduled=False`。实际事件：

```text
FailedScheduling  default-scheduler
0/5 nodes are available:
1 node(s) had untolerated taint(s), 4 Insufficient nvidia.com/gpu
```

其中 1 台控制面被污点排除，4 台 worker 各仅剩 3 卡，放不下申请 4 卡的 Pod。这不是 ImagePullBackOff，也不是 Kueue 队列配额不足。

```bash
kubectl --context kind-robot-train -n default get pods -l lab=l08 -o wide
kubectl --context kind-robot-train -n default describe pod l08-four-gpu
```

当前保留分散小任务和 Pending 的 4 卡 Pod，未整理布局、未改变 scheduler 配置。确认本段 YAML 与观测无疑问后，再进入集中放置对照与装箱策略。

### 追问：GPU 资源名是否原生，以及如何看 Events

Kubernetes 原生提供扩展资源（Extended Resources）的申报、计数和调度机制；`nvidia.com/gpu` 是 NVIDIA device plugin 通常使用的资源名，不是 Kubernetes 自动探测显卡后必然具备的内置 CPU / memory 类资源。真实集群通常要安装驱动、device plugin 并配置容器 GPU 运行环境；插件上报设备后才能分配并供容器使用。当前实验由 fake-gpu.sh 手动上报计数，没有真实设备，故能验证调度但不能运行 GPU 计算。

用户反馈未看到 Events，现场复查 `describe pod l08-four-gpu` 仍能在输出末尾看到 FailedScheduling 事件，单独 get events 也能读到；因此不能将本次情况归因为事件已过期。`get pod -o yaml` 不会附带 describe 中的事件列表，因为 Event 是独立资源。可以执行：

```bash
kubectl --context kind-robot-train -n default describe pod l08-four-gpu
kubectl --context kind-robot-train -n default get events \
  --field-selector involvedObject.kind=Pod,involvedObject.name=l08-four-gpu \
  --sort-by=.lastTimestamp
```

若事件已过期或列表为空，还可直接查看 Pod 当前的调度条件：

```bash
kubectl --context kind-robot-train -n default get pod l08-four-gpu \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} reason={.reason} message={.message}{"\n"}{end}'
```

本次输出为 `PodScheduled=False reason=Unschedulable`，Message 包含 `4 Insufficient nvidia.com/gpu`。当前未改变实验现场。

### 追问：fake-gpu.sh 如何上报模拟 GPU？

脚本没有模拟驱动或显卡运算，而是通过 Kubernetes API 修改各 Node 的资源声明。逐段对应 `robot-k8s-lab/fake-gpu.sh`：

1. `GPUS_PER_NODE="${GPUS_PER_NODE:-4}"`：读取环境变量，未设置或为空时默认每节点 4；不是集群总共 4。脚本使用当前 kubectl context，本次应为 kind-robot-train。
2. `kubectl get nodes -l '!node-role.kubernetes.io/control-plane' -o name`：选取没有控制面标签的 Node，返回 node/名称，依次处理本集群 4 个 worker。
3. `kubectl patch "$node" --subresource=status --type=json`：向 Node 的 status 子资源提交 JSON Patch；将 `/status/capacity/nvidia.com~1gpu` 设为字符串数量。路径中的 `~1` 是 JSON Pointer 对资源名内 `/` 的转义。`op: add` 在字段已存在时设置 / 替换其值，不是每运行一次加 4。
4. 节点状态效果为 `status.capacity: {nvidia.com/gpu: "4"}`。API Server 存储这份声明；对于这种手工上报的扩展资源，kubelet 后续状态更新使 allocatable 反映该数量，因此脚本等待同步。
5. 最多 30 次、每次间隔 2 秒检查 worker 的 allocatable 是否非空，再打印 capacity / allocatable。当前检查只看非空，若重跑改数量，不能证明 allocatable 已等于新值；等待耗尽也不主动报错，须核对最终输出。本次未改动脚本。

**allocatable 不等于剩余空闲量**：它是节点可供 Pod 分配的总额度。节点 allocatable=4、有 Pod 申请 1 时，该值通常仍为 4；调度器结合已有 Pod 的 requests 算出剩余 3。capacity / allocatable 不会因为每调度一个 Pod 就减去其申请量。

调度器按扩展资源名字与数量过滤节点，不在每次调度时检查对应的物理显卡是否真的存在。真实 device plugin 还参与设备发现和分配；当前只是写计数。pause 容器不访问 GPU，所以可运行，但换成 CUDA 程序不会凭空得到 GPU。这个机制与 Kueue 的 nominalQuota 又是两层：脚本声明节点资源，Kueue 定义队列配额。

参考：[Kubernetes 上报节点扩展资源](https://kubernetes.io/docs/tasks/administer-cluster/extended-resource-node/)。

> 检查问题：已有一个 Pod 申请 1 张卡后，节点 allocatable 会从 4 变成 3 吗？\
> 我的回答：不会。\
> 点评：正确。allocatable 仍为 4，表示可供 Pod 分配的总额度；调度器结合现有 Pod 的 requests 算出剩余 3。这里的“已用”是已申请 / 分配的资源量，不是 GPU 实时计算利用率。确认脚本讲解无疑问后，再继续集中放置对照实验。

### 6C：集中放置后，原 4 卡 Pod 自动运行（已验证）

新增并先讲解 `step6/packed-small.yaml`：Deployment `l08-small-packed` 设置 replicas=4，每个 Pod 申请 1 卡；`nodeSelector: {kubernetes.io/hostname: robot-train-worker}` 限制到同一台 worker。Deployment 通过 ReplicaSet 管理这 4 个副本，与 DaemonSet 每台一个的语义不同。该配置用于人工集中布局对照，不是 MostAllocated 自动评分演示。

server dry-run 通过后，先记录原 Pending Pod UID：`39c806e3-cf16-4b25-aa38-23cd96e6f825`。应用 packed Deployment，目标 worker 原有 1 个分散小 Pod，故先只有 3 个新 Pod Ready、第 4 个 Pending；此时原 4 卡 Pod 仍 Pending。随后删除 scattered DaemonSet，等待其 Pod 移除。这样目标节点一直有小任务占用，避免切换过程中 4 卡 Pod 抢先占住该节点。

```bash
kubectl --context kind-robot-train apply -f robot-k8s-lab/step6/packed-small.yaml
kubectl --context kind-robot-train -n default wait deployment/l08-small-packed \
  --for=jsonpath='{.status.readyReplicas}'=3 --timeout=40s
kubectl --context kind-robot-train -n default delete daemonset l08-small-scattered
kubectl --context kind-robot-train -n default rollout status deployment/l08-small-packed --timeout=40s
kubectl --context kind-robot-train -n default wait pod/l08-four-gpu --for=condition=Ready --timeout=40s
kubectl --context kind-robot-train -n default get pods -l lab=l08 -o wide
```

结果：4 个小 Pod 全部在 robot-train-worker 上 Running；原来的 l08-four-gpu 在 robot-train-worker3 上变为 `1/1 Running`，UID 保持不变，没有删除重建或降低其资源申请。没有增加物理资源，小任务总申请仍为 4 卡；集中放置留下完整空闲节点，让大 Pod 可调度。最终小任务共 4 卡、大 Pod 4 卡，总已分配 8，另有 8 卡空闲。

当前保留集中布局。确认本段配置与结果无疑问后，再学习调度器 MostAllocated 的自动装箱；本次还未更改任何 scheduler 配置，也不是已有 Pod 自动迁移。

### 追问：packed-small.yaml 两处 scenario 标签的关系

第 13 行属于 `spec.selector.matchLabels`，是选择条件；第 18 行属于 `spec.template.metadata.labels`，定义新建 Pod 携带的标签。模板标签必须满足 selector 中的全部条件，本例同时满足 lab=l08、scenario=packed-small。模板可以增加其他标签，不要求两块内容逐字完全相同；若模板不满足 selector，创建 / 更新 Deployment 会被校验拒绝。

`scenario` / `packed-small` 是本实验自定义的标签键和值，没有 Kubernetes 内置特殊语义。Deployment 通过 ReplicaSet 管理 Pod，标签选择器参与识别对应对象；ownerReferences 表达控制归属，不能把“任意 Pod 打相同标签”简单理解为一定被这个 Deployment 接管。`nodeSelector` 则匹配 Node 标签来限定运行节点，与这里选择 Pod 的 selector 是不同用途。

可以按这些 Pod 标签查询：

```bash
kubectl --context kind-robot-train -n default get pods -l lab=l08,scenario=packed-small
```

参考：[Deployment 标签选择器](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#selector)。

### 追问：究竟是谁按标签选中 Pod？

前文把“Deployment 通过标签管理 Pod”简写成了直接关系，需展开中间层：Deployment 控制器创建 / 管理 ReplicaSet，ReplicaSet 控制器按 ReplicaSet 的 selector 及控制归属管理 Pod 数量。集群实查：ReplicaSet 为 `l08-small-packed-95554c4f5`，owner 是 Deployment/l08-small-packed；4 个集中放置 Pod 的 owner 均为该 ReplicaSet。ReplicaSet 的 selector 含 lab=l08、scenario=packed-small，以及自动添加的 pod-template-hash=95554c4f5，用于区分模板版本。

这些控制器是 kube-controller-manager 中运行的控制循环，Deployment / ReplicaSet 则是 API 资源对象。选择器是匹配条件，ownerReferences 表示实际归属；标签本身没有执行管理的能力，也不是由 kube-scheduler 用这些 scenario 标签来确定 Pod 的控制器。只有 scenario 标签匹配不足以断言 Pod 被某个 ReplicaSet 控制。

```text
Deployment l08-small-packed
  → ReplicaSet l08-small-packed-95554c4f5
    → 4 个带匹配标签、owner 指向该 ReplicaSet 的 Pod
```

### 6D：MostAllocated 配置阅读（尚未启用）

用户确认标签选择器与归属无疑问；Pod ownerReferences 的查看方式包括 get pod -o yaml、jsonpath 读取 metadata.ownerReferences，或 describe 的 Controlled By。

新增 `step6/scheduler-config.yaml` 用于阅读，尚未运行验证或启用。它是 kube-scheduler 进程的组件配置，不是可 kubectl apply 的 API 资源。当前集群默认 scheduler v1.37.0 未读取此文件，集中布局现场保持不变。

- `kind: KubeSchedulerConfiguration`：配置调度器进程，与 Job / Deployment 配置不同。
- `profiles[].schedulerName: l08-binpack`：定义此 profile 的调度器名字。将来需启动读取该配置的调度器，并在 Pod spec 中设置 `schedulerName: l08-binpack` 才会使用它；只写 Pod 的 schedulerName 而没有对应调度器，会使其等待。
- `pluginConfig.name: NodeResourcesFit`：设置节点资源适配插件的参数。调度先过滤放不下的节点，再给可用节点评分。
- `scoringStrategy.type: MostAllocated`：倾向资源已分配比例更高的可用节点，尽量留下完整空闲节点。
- `resources: [{name: nvidia.com/gpu, weight: 1}]`：此插件按 GPU 的资源申请比例评分，weight 是该资源在插件内的评分权重，不是申请 1 张 GPU。CPU / 内存的硬约束仍检查，只是不列入这份 NodeResourcesFit 评分资源列表。其他评分插件仍会参与，不能据此保证所有 Pod 必然挤在一台。

这里的使用比例按 Pod requests 和节点 allocatable 计算，包含待调度 Pod 的需求，不看 GPU 监控中的实时计算利用率。MostAllocated 影响新 Pod 的节点选择，不会自动搬迁已运行 Pod，也不会把一个放不下的节点因高分变成可用。

预测题（待回答）：两台均为 4 卡，A 已申请 3 卡、B 已申请 1 卡；现在新 Pod 申请 1 卡，两台都满足其他条件，其他评分相同。MostAllocated 更倾向 A 还是 B？

参考：[Kubernetes 资源装箱配置](https://kubernetes.io/docs/concepts/scheduling-eviction/resource-bin-packing/)。

> 预测题回答：A。\
> 点评：正确。在其他约束和评分相同的题设下，MostAllocated 倾向将新 1 卡 Pod 放到已申请 3/4 卡的 A，放置后 A 为 4/4、B 仍为 1/4。若放到 B，则 A 为 3/4、B 为 2/4，空闲量更分散。评分权重不绕过节点资源不足等硬约束。当前 scheduler-config.yaml 仍未启用，等待确认配置无疑问后再进行运行验证。

### 追问：调度器配置的作用范围与 Pod 重启

- kube-scheduler 是 Kubernetes 原生控制面组件，MostAllocated 是原生插件支持的评分策略。KubeSchedulerConfiguration 是进程读取的组件配置，不是直接 kubectl apply 就会启用的 API 对象；需要启动读取该文件的调度器进程。
- 本实验计划使用独立的 l08-binpack 调度器。目标 Pod 写 `spec.schedulerName: l08-binpack`；Deployment / Job 则写在 `spec.template.spec.schedulerName`。其他使用 default-scheduler 的 Pod 不直接采用此策略，但仍共享同一节点资源池，存在资源占用上的间接影响。
- 普通调度器主要处理尚未分配节点的 Pod，不会因新调度器启用而自动迁移已运行 Pod。容器在原 Pod 内崩溃重启由 kubelet 处理，仍在原节点，不重新调度；修改 Deployment 的 Pod 模板触发替代 Pod 创建，或删除 Pod 后控制器补建，才涉及新 Pod 的调度。
- 新 Pod 用哪套调度器，仍取决于新模板的 schedulerName；仅删除重建但未改模板，不会自动采用 l08-binpack。对应调度器未运行时，指定其名字的 Pod 会等待。

用户确认上述区别理解。当前仅记录讲解，尚未部署独立调度器或改变集中布局；开始运行验证前再确认是否还有问题。

### 6E：独立 MostAllocated 调度器自动集中放置（已验证）

用户确认无疑问后，新增 / 修改配置并先逐段讲解：

- `scheduler-config.yaml`：增加 leaderElection.leaderElect=false（单副本教学进程不参与选主）；score 阶段禁用默认评分插件并单独启用 NodeResourcesFit，仍按 GPU 使用 MostAllocated。这样隔离其他评分干扰，默认 Filter 等阶段仍保留。这是教学实验配置，不代表生产应一律关闭其他评分。
- `scheduler.yaml`：创建 kube-system/l08-binpack ServiceAccount，绑定内置 system:kube-scheduler 与 system:volume-scheduler 角色；单副本 Deployment 启动与集群同版本的 kube-scheduler:v1.37.0。通过 ConfigMap 将组件配置挂载到 /etc/l08-scheduler/config.yaml，进程用 --config 读取。节点选择与容忍让这个不申请 GPU 的控制面组件运行在 control-plane；它自己的 Pod 由默认调度器处理。HTTPS /readyz、/healthz 用于就绪与存活检查。
- `auto-small.yaml`：Deployment 初始 replicas=1，每 Pod 申请 1 卡，Pod 模板指定 schedulerName=l08-binpack，没有 nodeSelector。通过 scale 从 1 → 2 → 3 → 4，每次等待 Ready 后观察节点。

Deployment、权限对象与 ConfigMap 均通过服务端校验。组件配置不是 API 对象，其可用性另由实际 scheduler 进程成功启动并就绪验证。创建 ConfigMap 的方式：

```bash
kubectl --context kind-robot-train -n kube-system create configmap l08-binpack-config \
  --from-file=config.yaml=robot-k8s-lab/step6/scheduler-config.yaml \
  --dry-run=client -o yaml > /tmp/l08-binpack-configmap.yaml
kubectl --context kind-robot-train apply -f /tmp/l08-binpack-configmap.yaml \
  -f robot-k8s-lab/step6/scheduler.yaml
kubectl --context kind-robot-train -n kube-system rollout status deployment/l08-binpack
```

启动成功后删除人工 packed Deployment 和原 4 卡 Pod，等待其退出，清空实验 GPU 占用。提交 auto-small 并逐个扩到 4，实测四个小 Pod 全部放到 robot-train-worker4；逐个读取 Pod，schedulerName 均为 l08-binpack，nodeSelector 为空。没有绑定目标节点，也没有沿用人工布局的小 Pod。

```bash
kubectl --context kind-robot-train apply -f robot-k8s-lab/step6/auto-small.yaml
kubectl --context kind-robot-train -n default rollout status deployment/l08-small-auto
# 依次用 2、3、4 执行下面两条，每次等待后再扩下一个副本。
kubectl --context kind-robot-train -n default scale deployment l08-small-auto --replicas=2
kubectl --context kind-robot-train -n default rollout status deployment/l08-small-auto
kubectl --context kind-robot-train -n default get pods -l scenario=auto-small -o wide
```

再通过原 four-gpu-pod.yaml 新建一个 4 卡 Pod（这次是新对象），由 default-scheduler 成功放到 robot-train-worker。新旧调度器均为 1/1 Running：四个小 Pod 自动集中占满 worker4，大 Pod 在 worker 上独占 4 卡，worker2 / worker3 各保留完整 4 卡空闲。

本次结果验证了自动评分效果；不同于 6C 的人工指定位置，也不同于迁移已有 Pod。默认调度器没有替换。第 6 步完成，保留实验现场；确认无疑问后进入第 7 步面试回顾与参考文档整理。

参考：[Kubernetes 多调度器](https://kubernetes.io/docs/tasks/extend-kubernetes/configure-multiple-schedulers/)。

---

## 第 7 步 · 综合面试口述与参考整理

用户确认自动装箱实验无疑问。已将已验证的调度结论、对象关联、关键字段、checkpoint 与排障命令整理到 `robot-data-reference.md` 第 11 节，并在面试笔记新增题 2。其他第二阶段专题尚未完成，本课也等待综合口述与点评后才标记收尾完成。

综合题：4 台 × 4 卡私有云共享集群，不加机器、不改模型 / 数据，如何解决多 worker 部分分配、团队共享、紧急任务资源交接与节点碎片？如何减少中断损失，用什么指标验证优化？允许用自然语言，不要求背 YAML 或 API 名称。当前等待用户回答，尚未清理实验现场。

第一轮口述已回答：Kueue 整体准入避免部分分配；配置 kube-scheduler 集中放置减少 GPU 碎片；withinClusterQueue=LowerPriority 配合 checkpoint 让紧急任务获得资源。点评：三项方向正确，需补齐团队配额 / 借用和验证指标；并区分配额准入与物理放置、队列内部抢占与跨队列回收、保存 checkpoint 与实际加载恢复。先追问团队份额与共享，不一次要求补完所有缺项。当前第 7 步仍进行中。

团队配额追问中，用户将两个 LocalQueue 各自设置 8 卡并连到同一 16 卡 ClusterQueue，再将 LocalQueue 连 Cohort。需再次澄清：LocalQueue 是入口；两个 ClusterQueue 分别设置 8 卡及借用上限，再以 cohortName 连到共享组。两份额合计 16，不另建一个 16 卡 ClusterQueue。用甲借 4 卡后查看哪个 ClusterQueue 的 total / borrowed 来确认记账对象。详细回答和点评同步到面试笔记，暂未进入指标追问。

用户确认 total=12 / borrowed=4 属于甲的状态，回答正确。接着补综合题的验证指标：优化后怎样证明 GPU 更少空转、任务交付更快，以及抢占没有造成过多重复计算？当前等待用户回答，收尾步骤仍未完成。

用户提出 Pending Pod / GPU 使用率、Job 从 suspend=true 到 false 的等待时间，以及驱逐时 checkpoint 数量。点评已同步面试笔记：前两项补齐 Workload 排队、分配与计算利用率、按团队 / 优先级的排队和端到端时延；第三项不能用保存次数代表重算成本，应观察完整 checkpoint 的进度损失及重算 GPU 时间、恢复开销与保存 I/O 成本。继续用 8 卡 × 6 分钟的抢占损失题确认成本单位，尚未标记第 7 步完成。

用户正确回答重算 6 分钟、8×6=48 GPU 分钟（0.8 GPU 小时），但随后要求先继续答疑，因此暂不收尾。

### 收尾追问：既有 ClusterQueue / Cohort，为什么还要 LocalQueue？

LocalQueue 把 namespace 内的任务提交入口，与集群级的资源配额管理分开。标准 Kueue 提交路径中，Job 的 queue-name 引用同 namespace 的 LocalQueue，再由 LocalQueue 指向 ClusterQueue。用户可通过列举自己 namespace 内 LocalQueue 发现提交入口；平台管理员集中管理 ClusterQueue 的额度和共享规则。

教学用单 namespace、一入口对一账本，容易显得冗余；更有意义的例子是同一团队有 robot-dev / robot-eval 两个 namespace，各自都建名为 train 的 LocalQueue，共同指向 team-a-cq，合计共享其 8 卡份额，而非各获得 8 卡。两边 Job 都可写 queue-name: train，名称在各自 namespace 解析。ClusterQueue 无 namespace，同一个可被多个 LocalQueue 引用。

LocalQueue 不是额外的独立 GPU 份额，也不是团队间借用的执行者；借用规则仍在 ClusterQueue / Cohort。权限控制还需 RBAC、ClusterQueue 的 namespaceSelector 等配套，并非创建 LocalQueue 就自动完成租户隔离。本课 default 下放甲乙两个入口只为聚焦配额，不代表生产权限设计。

“需要 LocalQueue 对象”不等于“需要额外一个 YAML 文件”：可以和 ClusterQueue / Cohort 写在同一文件，用 --- 分隔；本课 step4/queues.yaml 已经如此组织。默认 LocalQueue 功能可省去部分 Job 标签填写，不是绕过 LocalQueue 直接提交到 ClusterQueue。

参考：[Kueue LocalQueue](https://kueue.sigs.k8s.io/docs/concepts/local_queue/)。

> 检查问题：开发和评估各有一个 LocalQueue，都指向同一个 8 卡 ClusterQueue，合计名义份额是多少？\
> 我的回答：还是 8。\
> 点评：正确，两个入口共用同一账本，不会复制额度。当前等待用户确认是否还有其他疑问，暂不收尾或进入下一课。

### 本课收尾（已完成）

用户确认其余问题已解决并授权继续。综合题的初答、团队配额纠正、LocalQueue 作用、指标与抢占成本换算均完成；最终口述版和实验能力边界已写入 `robot-data-interview-notes.md` 题 2。`robot-data-reference.md` 第 11 节整理已验证结论、对象关系、关键字段、checkpoint 与排障命令。

验证指标：GPU 分配率对比实际利用率；按团队 / 优先级比较 Workload 排队时间、准入到 worker 全就绪时间、端到端完成时间和吞吐；单独统计资源碎片和等同伴造成的浪费，以及 checkpoint 保存 / 加载和重算 GPU 小时。8 卡 × 6 分钟 = 48 GPU 分钟 = 0.8 GPU 小时，不含启动 / 加载开销。当前仅有模拟调度证据，没有真实训练性能或业务恢复验证。

后续教学约定：面试练习也按“回答 → 点评 / 追问 → 确认是否还有问题 → 下一题”进行；新增 YAML / 代码先带读教学字段，再执行。此约定同步面试笔记。

L08（第二阶段专题 D）完成，其他专题尚未完成。后续建议顺序为训练数据管线（B）→ 成本模型（E）→ 系统设计（F），真实训练恢复（C）与视频压缩过滤（A）按需深入。当前教学集群保持装箱实验现场，没有删除集群或进入新专题。
