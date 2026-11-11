# scratch —— 阶段 1/2 学习脚本

配套 `docs/ai-agent-learning/`。这里是**可运行、带练习**的裸调脚本，用来打通 roadmap 的
**阶段一（LLM API 基础）**和**阶段二（Prompt Engineering）**。

> 这些是学习脚本，不是业务代码。代码修改仍须遵守仓库 `AGENTS.md`：附对应测试并保持已有测试通过。

## 前置：安装依赖

### L14：成本估算器（已完成）

`load_scenario()` 将UTF-8 JSON文件读为配置字典；`estimate_scenario()` 接收字典，串联上传量、带宽、原始/派生存储、训练和checkpoint计算，返回各项明细与所列项目月费合计。示例配置为 `robot-cost-lab/baseline.json`；原始视频每日入库量从上传量传入，不重复手填。CLI已可运行（仓库根目录）：

```bash
backend/.venv/bin/python -m backend.scratch.robot_cost_model \
  backend/scratch/robot-cost-lab/baseline.json \
  --compare backend/scratch/robot-cost-lab/candidate.json \
  --upfront-cost 1000
```

不加 `--compare` 即只估算原方案；比较命令输出两份明细和净节省/回本，示例分别10880与12200元/月，净节省−1320元、回本为null。仅覆盖列明教学项目，质量与业务约束需另行检查。

`compare_costs()` 比较同范围月费，返回净节省与一次性投入的简单回本月数；净节省非正时回本为None，不代替质量及业务评估。

`checkpoint_overhead()` 汇总月度重算与额外保存/加载的GPU小时，以及checkpoint存储读写费；输入须排除与正常训练和其他存储项重复的部分。

`training_compute_cost()` 按固定GPU卡数、每次占用时长及每月运行次数计算GPU小时和折算月费，未加入checkpoint等额外开销。

`storage_estimate()` 估算保留窗口积累满后的逻辑GB、副本物理占用和按逻辑GB计费的月费，副本数不再乘入月费；物理占用未含预留空间，不是裸盘采购规格。

`robot_cost_model.py` 提供 `daily_video_volume()`，根据机器人 / 相机数量、平均码率、每日录制时长及上传字节比例，分别返回每日采集与上传的十进制 GB；`required_upload_mbps()` 根据上传量及上传窗口计算平均有效吞吐 Mbps。逐函数讲解见 `docs/ai-agent-learning/lessons/L14-robot-cost-estimator.md`，对应测试为 `tests/test_robot_cost_model.py`。

### L13：小型视频训练与 checkpoint（已完成）

```bash
# 仓库根目录，生成新目录中的视频和动作清单；已有同名输出会拒绝覆盖。
backend/.venv/bin/python -m backend.scratch.robot_video_data \
  --output-dir backend/scratch/robot-video-lab/training-demo-state
# 后端目录：对应数据测试
cd backend
.venv/bin/python -m pytest -q tests/test_robot_video_data.py
```

16 段 FFV1 无损合成视频，每段 8 帧、8 fps、32×32，示范脚本记录下一步水平位移。先按 episode 分组，再构建三帧窗口，训练 60 样本 / 验证 20 样本。schema_version=2 添加与窗口末帧同时间的模拟二维本体位置，归一化为 state=[x/31,y/31]，另保留原始值 / 时间供检查；模型输入是图像和当前状态，不输入未来状态或动作标签。实际视频解码后在内存缓存。旧版 training-demo 不覆盖，使用新目录 training-demo-state。`robot_video_model.py` 实现小 MLP 融合前向；`robot_video_train.py` 提供 `train_step()`、`train_epoch()`、`evaluate()`、`fit()`，整轮损失按样本数加权，对应测试为 `tests/test_robot_video_model.py` 和 `tests/test_robot_video_train.py`。共享内存受限环境中 PyTorch CLI 可能报 OpenMP Can't open SHM，需要正常共享内存权限。详见 `docs/ai-agent-learning/lessons/L13-robot-video-training-checkpoint.md`。

30 轮实测训练误差很低而验证误差仍高，呈过拟合迹象，不能宣称任务质量达标。实验曲线在忽略目录的 history-30epochs.json，历史记录不是 checkpoint。`robot_video_checkpoint.py` 已实现 `save_checkpoint()` / `load_checkpoint()`：在 CPU / num_workers=0 / 整轮边界保存模型、Adam、进度、配置、清单指纹和 RNG，先写临时文件再发布，不覆盖已有版本；恢复前检查配置 / 数据 / 结构，最后恢复 RNG，对应测试为 `tests/test_robot_video_checkpoint.py`。已实际保存第 5 轮 / 40 步的 epoch-005.pt（二进制忽略），并在新进程恢复核对相同验证结果。

跨进程续训对照 CLI：

```bash
backend/.venv/bin/python -m backend.scratch.robot_video_resume_demo \
  --manifest backend/scratch/robot-video-lab/training-demo-state/manifest.json \
  --output-dir backend/scratch/robot-video-lab/training-demo-state/resume-comparison \
  --mode prepare
# 随后另起命令：相同路径，--mode 改为 resume，再改为 without-adam。
```

prepare 保存连续 10 轮参考与第 5 轮中断点；resume 新进程完整恢复到第 10 轮，与参考权重 / Adam / RNG 精确一致；without-adam 只重置 Adam、保持同权重和随机状态，后续更新发生分歧。对应真实多进程集成测试为 `tests/test_robot_video_resume_demo.py`。已有阶段产物拒绝覆盖，报告 / checkpoint 留在忽略目录。此对照验证恢复技术，不等于模型质量达标，不代表 GPU / 分布式也必然逐位一致。

### L12：视频压缩与端侧过滤实操

视频工具安装在项目虚拟环境中（仓库根目录执行）：

```bash
backend/.venv/bin/python -m pip install --only-binary=:all: imageio-ffmpeg==0.6.0
```

本机验证该版本的 macOS ARM64 包内含 FFmpeg 7.1，支持 libx264；通过 Python 的 `imageio_ffmpeg.get_ffmpeg_exe()` 获取可执行路径，不依赖系统 PATH，也不包含 ffprobe。已在 `robot-video-lab/source.mkv` 生成 8 秒 / 640×360 / 30 fps 的 FFV1 无损测试源，完整回读验证 240 帧与生成源像素哈希一致；该媒体由目录内 .gitignore 排除，复现命令、压缩对照和测量边界见 `docs/ai-agent-learning/lessons/L12-robot-video-compression-filtering.md`。

端侧过滤对照（先讲解代码再运行，输出目录不可包含同名实验文件）：

```bash
backend/.venv/bin/python -m backend.scratch.robot_video_filter \
  --output-dir backend/scratch/robot-video-lab/filter-demo
# 后端目录执行对应测试
cd backend
.venv/bin/python -m pytest -q tests/test_robot_video_filter.py
```

生成三段 FFV1 无损合成视频，真实解码后比较“仅变化阈值”与“已知事件保护”。只生成报告、选择完整片段，不删除原文件。contact 元数据由实验构造，不代表算法从图像识别了接触；无此信号的关键事件仍可能漏掉。报告中的保留字节数不是实际网络费用，筛选也有解码与计算开销。媒体和报告在 filter-demo 下忽略，脚本与测试纳入版本管理。

### L09：机器人训练数据管线基线

```bash
# 仓库根目录；不需要 bridge、外部数据集或 GPU。
backend/.venv/bin/python backend/scratch/robot_pipeline_baseline.py
backend/.venv/bin/python backend/scratch/robot_pipeline_baseline.py --batch-size 10
# 配套测试及后端回归
cd backend
.venv/bin/python -m pytest -q tests
```

`robot_pipeline_baseline.py` 在临时目录生成 4 个合成 episode，前三个训练（48 个三帧窗口）、最后一个验证。测量真实 PNG 字节读取、像素解码、缩放 / 归一化及默认组 batch；固定 num_workers=0、CPU 张量计算线程数 1，不执行视频解码、设备传输或模型训练。刚生成的数据可能命中 OS 缓存，结果不是磁盘冷读 / 真实视频性能。计时不包含数据生成，退出后清理临时数据；动作是用于检查配对的合成标记。

讲义：`docs/ai-agent-learning/lessons/L09-robot-training-data-pipeline.md`。测试：`backend/tests/test_robot_pipeline_baseline.py`。

并行对照（仓库根目录，使用模块方式启动）：

```bash
backend/.venv/bin/python -m backend.scratch.robot_pipeline_parallel
# 同一设置的轮数、批大小和预取因子可通过参数改变；一次比较时其余条件保持一致。
backend/.venv/bin/python -m backend.scratch.robot_pipeline_parallel --epochs 3 --batch-size 8 --prefetch-factor 2
```

复用相同 Dataset，比较 0 个加载进程、2 个不保留进程、2 / 4 个保留进程；每项默认连续三轮，记录首批等待、每轮总时间和 PID，检查样本覆盖与配对。只测加载，没有训练计算，因此不能从该实验直接推断准备数据与 GPU 计算的重叠效果。固定 Mac / Python 3.12 / torch 2.2.2 环境有资源跟踪器退出兼容处理，依据上游 [3a7ff82](https://github.com/pytorch/pytorch/commit/3a7ff82)，仅在此模块的进程内生效，不修改依赖文件。多进程测试需要操作系统共享内存权限，受限沙箱中可能报 Can't open SHM。

阶段四之后的脚本（embedding、向量库、重排等）需要额外依赖，已声明在 `backend/pyproject.toml` 的 `scratch` 可选组里（版本钉死）：

```bash
cd backend
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,scratch]"
```

## 前置：启动 bridge

脚本通过官方 `anthropic` SDK 调用，但把 base_url 指向本地 **claude-cli-bridge**，
后者用你本地的 `claude` CLI（订阅）应答，**无需 ANTHROPIC_API_KEY**。

另开一个终端：

```bash
bash backend/scratch/run_bridge.sh
# 保持它运行，看到 "Uvicorn running on http://127.0.0.1:8787" 即就绪
```

## 跑脚本

```bash
cd backend
.venv/bin/python scratch/s1_01_first_call.py       # 第一次调用（结构化输出）
.venv/bin/python scratch/s1_02_streaming_events.py # 看清流式底层事件
.venv/bin/python scratch/s1_03_multiturn.py        # 上下文即内存（无状态）
.venv/bin/python scratch/s2_01_prompt_shaping.py   # 玩转仓库真实评估 prompt
.venv/bin/python scratch/s2_02_structured_json.py  # 结构化输出 + 扛刁钻输入
```

每个脚本文件末尾/中部都有 **`练习 TODO`**，改完重跑观察变化——这才是学习的核心。

## ⚠️ bridge 的限制（背后是 Claude CLI，不是真实 API）

| 能力 | bridge | 说明 |
|---|---|---|
| 消息角色 / system prompt | ✅ | 正常 |
| 流式 SSE 事件 | ✅ | 但只吐 tool_use，不吐纯文本 |
| tool / 结构化输出 | ✅ | **每次调用必须带 tool**，否则 400 |
| 纯文本回答 | ❌ | 硬性要求工具 JSON |
| 真实 token 计数 | ❌ | usage 恒为 0 |
| temperature | ❌ | 参数被忽略 |
| max_tokens 截断 | ❌ | 参数被接住但从不转发给 CLI，回答不会被截断，stop_reason 恒为 tool_use |
| 合法 JSON 保证 | ⚠️ | 偶发「格式跑偏」（未转义引号等），脚本已用重试 + 优雅降级处理 |

代理注意：本机设了 `HTTP_PROXY=127.0.0.1:8002`，会劫持发往 localhost 的请求。
`_bridge.py` 已用 `trust_env=False` 的 httpx 客户端绕开，无需你操心。

## 「需真 key」才能练的部分

以下目标 bridge 覆盖不了，拿到真实 `ANTHROPIC_API_KEY` 后再练（各脚本文末/TODO 处有说明）：

- **真实 token 用量 / 成本量级**（`s1_02` 里 usage=0）。
- **temperature / top_p 采样对照实验**。
- **纯文本对话**（不带 tool 的自由回答）。
- **`max_tokens` 截断**（`s1_02` TODO#1）：bridge 吞掉 `max_tokens`，回答不会被截断、`stop_reason` 也不会变成 `max_tokens`；真实 API 上把 `max_tokens` 调小会看到回答硬截断 + `stop_reason == "max_tokens"`。
- **删「必须调用工具」看输出稳定性**（`s2_02` TODO#2）：bridge 在 prompt_builder 里硬加「必须只输出工具 JSON」并强制解析工具调用，无视你的 system 指令，所以删掉那句也没差别；真实 API（tool_choice=auto）上删掉后模型可能改用自由文本、不调工具，导致结构化输出不稳定。真正的硬保证是 `tool_choice`，不是 system 里的一句话。

切真实 API：设 `ANTHROPIC_API_KEY`，把 `_bridge.py::BRIDGE_BASE_URL` 去掉（用官方默认地址）。

## 与 roadmap 的对应

| 脚本 | roadmap 阶段 | 学到的核心概念 |
|---|---|---|
| s1_01 | 一 | model/system/messages/tools 四要素、结构化输出 |
| s1_02 | 一 | 流式事件、增量 JSON、（token 概念） |
| s1_03 | 一 | 无状态、上下文即内存 |
| s2_01 | 二 | prompt 即代码、复用仓库真实 prompt、失败模式 |
| s2_02 | 二 | JSON Schema 强约束、enum 校验、prompt injection 防御 |

学完这 5 个脚本 + 做完各自 TODO，阶段一/二的验收标准（见 `00-roadmap.md`）基本达成，
下一步就能进阶段三（`02-tooluse-refactor.md`）。
