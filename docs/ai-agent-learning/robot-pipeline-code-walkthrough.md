# L09 · PyTorch 基础与 robot_pipeline_baseline.py 代码导读

> 配套代码：`backend/scratch/robot_pipeline_baseline.py`；讲义：`lessons/L09-robot-training-data-pipeline.md`。
> 本次暂停多进程实验，只解释现有串行代码，没有修改 Python 实现。使用本机 PyTorch 2.2.2。

## 1. 先认识 PyTorch 在这里做什么

PyTorch 是用于数值计算、自动求导、构建和训练神经网络的框架。常用部分有 Tensor（多维数字数组）、autograd（自动求梯度）、nn（网络层 / 模型）、optim（优化器）、utils.data（样本与批量读取）。本脚本只用 Tensor 运算与 utils.data，没有网络、loss、backward 或 optimizer.step，没有训练模型，所有张量在 CPU 上。

Tensor 的三个常见属性是 shape（各维长度）、dtype（每个数的类型）、device（数据在哪个计算设备上）。例如一帧 RGB 图像可表示为 [高, 宽, 3] 个像素值，本脚本将每个样本的三帧整理为 [3帧, 3通道, 112高, 112宽]。张量的各维含义由代码约定，不是 PyTorch 看见数字 3 就自动知道是 RGB 或帧数。

基础操作示意（不属于训练循环）：

```python
x = torch.tensor([0, 128, 255], dtype=torch.float32)
y = x / 255  # 约为 [0.0, 0.502, 1.0]
```

创建张量不会自动启动 GPU 计算或训练。通常张量默认在 CPU，需显式设备传输或由框架管理。张量也不因创建出来就自动需要梯度，本脚本没有启用训练求导。

## 2. 执行地图：先看 main，再逐个函数

```text
if __name__ == "__main__": main()
  → argparse 读取 batch-size，默认 8
  → torch.set_num_threads(1)
  → TemporaryDirectory 创建临时数据目录
  → make_fixture：生成 PNG 与 manifest
  → RobotWindowDataset：读取 manifest 并选训练记录
  → measure：创建 DataLoader，迭代全部 batch，累计计时
  → 退出临时目录作用域，清理数据
  → 打印加载结果
```

`torch.set_num_threads(1)` 控制 PyTorch CPU 算子使用的 intra-op 线程数，不等于 DataLoader worker 数，也不限制所有第三方库的所有线程。本次 DataLoader.num_workers=0，加载仍在主进程。

main guard 避免文件被 import 时立即生成数据、运行基准，后面 Mac spawn 多进程也需要这种入口保护。`argparse` / `Path` / `TemporaryDirectory` / `perf_counter` 属于 Python 标准库，不是 PyTorch。

## 3. make_fixture：造出可检查的教学数据

参数默认 episodes=4、samples_per_episode=16、image_size=96。固定 NumPy seed=42，便于重复生成相同图像内容，但这不固定操作系统调度或耗时。

每个 episode 生成 18 张 96×96 RGB PNG：每帧由形状 [96,96,3]、uint8 类型的随机像素数组保存而来。三帧滑动窗口可从 18 张图得到 16 个样本：

```text
anchor=2：帧 0、1、2
anchor=3：帧 1、2、3
...
anchor=17：帧 15、16、17
```

第 0 / 1 / 2 个 episode 为训练集，共 48 样本；第 3 个为验证集，共 16 样本。每个 episode 与自己的帧文件不跨集合。manifest.json 是样本目录清单，不含已经解码的图像张量。一条记录示意：

```json
{
  "sample_id": "0:2",
  "episode_id": 0,
  "anchor_frame": 2,
  "split": "train",
  "frame_paths": ["episode-0/0000.png", "episode-0/0001.png", "episode-0/0002.png"],
  "action": [0.0, 2.0]
}
```

action 仅是 [episode 编号, 锚点编号] 的合成检查标记，没有真实机器人控制含义。图像也是随机噪声，不表示抓取行为；这些数据用于验证加载机制、配对和计时，不能训练有用的策略。

## 4. RobotWindowDataset：规定如何取一个样本

该类继承 torch.utils.data.Dataset，实现 map-style Dataset 的常见接口：

| 方法 | 何时调用 | 本例作用 |
|---|---|---|
| __init__ | 创建实例 | 读 JSON 清单、过滤 split，保存路径与输出尺寸 |
| __len__ | len(dataset) | 返回所选集合样本数，默认 48 |
| __getitem__ | dataset[index]，或 DataLoader 取样时 | 读取三帧、解码、预处理，返回一个字典 |

**创建 Dataset 不等于把全部图像加载进内存。**本例构造时只读清单，图片在具体取样时才读。DataLoader 通过这些接口取数据，但 Dataset 本身不决定一次组几批或模型如何更新。

### 4.1 read：磁盘文件到压缩字节

```python
encoded = [(self.root / name).read_bytes() for name in record["frame_paths"]]
```

取当前记录的三条相对路径，拼根目录，读取每个 PNG 的 bytes。此时得到压缩文件内容，不是可直接供图像模型使用的像素张量。相邻样本共享帧，但脚本没有显式图像缓存，会再次读取 / 解码，操作系统文件缓存可能命中。

### 4.2 decode：压缩字节到像素

```python
with Image.open(io.BytesIO(payload)) as image:
    image.load()
    frames.append(image.convert("RGB"))
```

BytesIO 将内存 bytes 包装为类文件对象。Pillow 的 Image.open 可能延迟实际像素解码，因此显式 load，让解码工作确实落在 decode 计时段。convert("RGB") 统一通道格式。这里是 PNG 图像解码，不是 MP4 / H.264 视频解码。

### 4.3 preprocess：尺寸、维度与数值类型

先将三帧各自缩放至 112×112，转换为 NumPy 数组，每帧形状 [112,112,3]。随后这条链：

```python
images = torch.from_numpy(np.stack(arrays)).permute(0, 3, 1, 2).float().div_(255)
```

拆开后为：

| 操作 | 结果形状 / 类型 | 含义 |
|---|---|---|
| np.stack(arrays) | [3,112,112,3]，uint8 | 为三帧增加帧维，不是首尾接成长图 |
| torch.from_numpy(...) | 同形状 uint8 Tensor | 从 NumPy 数组建立张量；此操作与数组共享底层内存，后续 float 会转换类型 |
| permute(0,3,1,2) | [3,3,112,112] | 将原维度按“帧、通道、高、宽”排列，不改变帧时序，也不是 reshape 乱排数值 |
| float() | float32 | 将整数像素转换为浮点数，张量形状不变 |
| div_(255) | 浮点 [0,1] | 原地除以 255；下划线表示原地操作 |

从原轴 [0帧,1高,2宽,3通道] 取 [0,3,1,2] 就得到目标轴顺序。这里的两个 3 含义不同：一个是 3 帧，一个是 RGB 三通道。permute 通常返回共享底层存储的视图，可能不连续；不必为本例先深入 stride。

```python
action = torch.tensor(record["action"], dtype=torch.float32)
```

将当前样本的目标标记也转成张量，shape=[2]。返回字典还包括 sample_id / episode_id / anchor_frame，以及三段耗时。图像与目标取自同一 record，避免分别随机读取而错配。

### 4.4 如何计时

用 perf_counter 在读文件前、读后、解码后、预处理后打点，时间差乘 1000 得到毫秒。各段具体包含什么由打点位置决定：例如本例 preprocess 也包含动作张量构造，不只 resize。它是 CPU 同步计时；未来真实异步 GPU 计时不能不加处理直接照抄。

## 5. timed_collate：将样本字典列表拼成 batch

DataLoader 取到 8 个样本后，把列表交给 timed_collate。内部 default_collate 按同名字段组装：

```text
8 个 samples：各 images 为 [3,3,112,112]，各 action 为 [2]
  → 一个 batch 字典
      images：[8,3,3,112,112]
      action：[8,2]
      sample_id：8 个字符串组成的列表
      timing_ms：read / decode / preprocess 各有 8 个数值的张量
```

它不是把 images 和 action 合成一块，也不会混淆第 i 个图像和第 i 个目标。内部计时之后补上一个 collate_ms 数值。计时包含默认组装的全部字段（含元数据、计时值），因此此脚本的吞吐也包含测量开销。

## 6. measure：驱动 DataLoader 并累计结果

```python
loader = DataLoader(dataset, batch_size=batch_size, num_workers=0,
                    shuffle=False, drop_last=False, collate_fn=timed_collate)
```

各参数分别控制样本来源、每批数量、加载子进程数、是否随机取样、是否丢尾批、怎样拼 batch。此时只创建 loader，不会立即完整读取所有图片；for batch in loader 才开始逐批取数据。

一次循环默认涉及 8 次 Dataset 取样，再组 batch；完整 48 样本共 6 次循环。sample_ids 用于检查覆盖情况，batch_sizes 记录尾批是否保留。

```python
batch["timing_ms"][name].sum().item()
```

sum 将本批每个样本该阶段耗时相加，得到标量 Tensor；item 将单元素 Tensor 转成 Python 数字，再加到全轮累计。它不是模型 loss，也没有更新参数。总时间覆盖 for 循环中的迭代与统计，吞吐为已输出样本数 / 总秒数。构造 Dataset 和生成文件的时间没有计入。

基线串行时四段累计时间约接近总时间，但存在额外开销。将来多 worker 并发时，各进程累计工作时间之和不能当作真实经过的总时间。

## 7. main：如何跑，以及实际读到了什么

```bash
backend/.venv/bin/python backend/scratch/robot_pipeline_baseline.py
backend/.venv/bin/python backend/scratch/robot_pipeline_baseline.py --batch-size 10
```

第一条默认批大小 8，输出 6 个完整 batch；第二条批大小 10，48 样本的批大小为 10 / 10 / 10 / 10 / 8。每次生成临时数据，退出后删除；不是操作业务库或私有云数据。

2026-11-02 已另做一次取样与组批核对：len(dataset)=48；sample["images"] shape=[3,3,112,112]、dtype=float32、device=cpu；第一个 action=[0.0,2.0]；第一批 images=[8,3,3,112,112]、action=[8,2]，sample_id 为 0:2 到 0:9。此次用于确认形状，不重新做性能结论。

## 8. 测试守住哪些边界

`backend/tests/test_robot_pipeline_baseline.py` 验证训练与验证 episode / 帧不重叠；窗口时序和动作标记一致；图像张量形状、类型、范围正确；重排样本后配对不变；完整遍历无漏样本且保留尾批；缺帧显式报错、不悄悄跳过；非法配置被拒绝。测试不要求某台机器必须达到固定吞吐。

这份脚本没有模型、loss、梯度计算或参数更新。它只测训练之前的加载路径，也没有执行真实视频解码、GPU 传输、私有云读取或真实机器人策略评估。

参考：[PyTorch Tensor 基础](https://docs.pytorch.org/tutorials/beginner/basics/tensorqs_tutorial.html)、[Dataset / DataLoader 入门](https://docs.pytorch.org/tutorials/beginner/basics/data_tutorial.html)。

## 9. 课堂确认：图片何时加载？

用户回答：“要等到 measure 函数被执行时，才开始加载图片。”在当前 main 调用路径中判断正确，进一步精确到 `measure()` 中开始迭代 `for batch in loader`，才触发 Dataset 的取样和读取；进入 measure 或仅构造 DataLoader 不会完整读入图片。也可以不经过 measure，直接调用 dataset[0] 触发单样本加载。当前 num_workers=0，在主进程依次取样；未来多进程预取可能在迭代器建立后就提前启动取样，不能认为只有训练循环消费到某个样本时才会读取它。

用户要求暂停课程推进、逐个答疑。第一个问题澄清：torch.tensor([0,128,255]) 中三个数字是元素值，shape=[3] 才表示一维长度 3；二维列表 2 行 3 列的 shape=[2,3]。元素值与维度长度是两层信息。

第二个问题澄清：4 个 episode 不共用同一组 18 张图，每段在各自目录生成 18 张，总计 72 张；每段形成 16 个三帧窗口，总计 64 样本，其中训练 48、验证 16。同 episode 相邻窗口复用帧，跨 episode 不复用帧文件。窗口是有序的三帧样本引用，脚本没有编码生成三帧视频文件；图像是随机合成，也不构成真实连续运动。

### 图像尺寸、通道及维度顺序追问

3 通道来自 RGB（三个颜色分量）；112×112 来自 Dataset 构造参数 output_size=112 和 resize。原始合成 PNG 为 96×96，处理后统一为 112×112；尺寸是实验设置，不是 PyTorch 固定要求。

Tensor 允许把同一数据按不同逻辑轴顺序表示，例如 [帧,通道,高,宽] 或 [高,宽,通道,帧]，但后续模型 / 算子必须按匹配的输入约定读取。Tensor 本身不识别哪根轴是时间或颜色；常见批量 Conv2d 输入按 [batch,通道,高,宽]，视频模型的帧 / 时间轴约定则因模型而异，不能假设本脚本的 [batch,帧,通道,高,宽] 适用于所有模型。

从 [F,C,H,W] 转成 [H,W,C,F] 使用 `x.permute(2,3,1,0)`；转回使用 `y.permute(3,2,0,1)`。permute 调整轴顺序和相应索引关系，不是只改名字，也不能用任意 reshape 冒充换轴。实测 [2,3,4,5] → [4,5,3,2]，x[1,2,3,4] 与 y[3,4,2,1] 值相同，转回与原张量相等。

本脚本采用 FCHW，只是一种明确的数据接口约定，未包含模型。两个 3（帧数 / 通道）、两个 112（高 / 宽）恰好相同，即使错误换轴，shape 也可能看起来没变，不能只按 shape 数字判断语义正确。当前仍停在逐个答疑，未继续并行实验。

### 术语回顾：张量与轴编号

在当前 PyTorch 语境中，可先把 Tensor（张量）理解为带 shape / dtype / device 的数字数组：单个数是 0 维张量，数字列表是一维，行列表格是二维，图像及视频批次可有更多维度。这是编程入门理解，不展开数学中张量的严格变换定义。维度数是轴的个数，不是元素数量；[0,128,255] 有 3 个元素但只有一维，shape=[3]。

用户追问 permute(0,3,1,2) 的编号来源：np.stack(arrays) 的原轴为 0帧 / 1高 / 2宽 / 3通道；目标顺序是帧 / 通道 / 高 / 宽，所以依次取原轴 0 / 3 / 1 / 2。这些数是轴编号，不是像素值或维度长度。

用户追问批量图像大小公式中最后的 4：它是 float32 每元素 4 字节，32 bit÷8=4 Byte，由本脚本 `.float()` 所选类型决定。Tensor.numel() 返回元素总数，element_size() 返回每元素字节数，两者相乘为数据载荷大小，不是程序全部内存。

## 10. 并行对照脚本的新增逻辑

用户确认前述逐个答疑均结束，再继续 `backend/scratch/robot_pipeline_parallel.py`。串行 baseline 保持原样，新脚本通过模块导入复用 Dataset，不改变三帧窗口、像素处理或动作标记。

- `build_loader()`：固定 batch_size / shuffle=False / drop_last=False，只改变 worker 设置；num_workers>0 才传 prefetch_factor、persistent_workers、spawn 和 worker_init_fn；0 worker 时不传这些参数。
- `init_worker()`：每个加载进程的 PyTorch CPU 算子线程设为 1，避免把进程数增加与算子内部线程增加混在一起。仍非所有第三方线程的全局限制。
- `collate_with_pid()`：复用 timed_collate，然后加当前 os.getpid()，直接证明组批由主进程还是加载进程执行，以及各轮是否复用。
- `run_epoch()`：开始迭代前计时，记录首批等待和完整一轮，检查目标标记与 episode / anchor 一致、样本顺序和覆盖与清单一致。阶段耗时是加载工作量之和，不是多个进程并发后的墙钟总耗时。
- `benchmark_setting()`：同一个 DataLoader 连续迭代多轮，然后销毁并清理；若每轮重建 DataLoader，就无法证明 persistent_workers 的跨轮次复用。0 worker / 2 不保留 / 2 保留 / 4 保留分别执行。
- `main()`：先生成同一份临时 PNG 数据，各设置依次运行，打印每轮时间、首轮首批等待和后续轮次中位数。文件缓存、执行顺序与短轮次噪声存在，后续中位数不等于经过严格稳态性能验证。

计时边界：首批包括启动 / 重置迭代器和等待数据；不保留 worker 时，for 循环结束的进程退出开销也在该轮计时内。保留 worker 的最终统一清理在各轮计时外，不能把两组的每轮时间当作完全等价的进程生命周期成本。当前实验无模型计算，不验证 GPU 与准备数据重叠，也未测内存峰值或单独比较不同 prefetch_factor。

运行环境中发现 Python 3.12.14 / torch 2.2.2 的进程退出等待，采样为 Py_FinalizeEx → ResourceTracker finalizer → waitpid，与上游 [问题 #153050](https://github.com/pytorch/pytorch/issues/153050) 一致。新脚本在精确限定的 macOS / Python 3.12 / torch 2.2.2 组合内，采用上游 [3a7ff82](https://github.com/pytorch/pytorch/commit/3a7ff82) 同类处理，跳过资源跟踪器的退出析构等待；普通 DataLoader worker 的停止机制仍保留，不使用 os._exit，也不修改 site-packages。升级依赖后需重新评估，不把它当作训练业务逻辑。新增真实子进程 CLI 回归检查程序是否正常退出，避免只看到测试成功输出就忽略退出挂起。
