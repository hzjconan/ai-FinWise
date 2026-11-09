# L13 · 小型视频训练与 checkpoint 恢复实操（第二阶段专题 C）

> 状态：已完成（2026-11-09）。前置 L09 数据管线、L12 视频实操；本课真正读取编码视频、训练小模型并演练恢复，不把加载或压缩误称为训练。CPU 规模，先讲代码再运行，每段点评后确认有无疑问。新增代码附对应测试；参考整理至 robot-data-reference.md 第 16 节，代码与课堂记录保存进度。

## 目标与步骤

| 步 | 内容 | 状态 |
|---|---|---|
| 1 | 定义视频输入、示范动作标签与任务边界 | ✅ |
| 2 | 生成并解码小视频数据，按 episode 划分，再构建时序窗口 | ✅ |
| 3 | 阅读小模型、前向预测、loss 与优化器代码 | ✅ |
| 4 | 真正训练，比较训练前后与独立验证结果 | ✅ |
| 5 | 保存、中断和恢复；对比仅恢复权重与完整状态 | ✅ |
| 6 | 复盘、面试口述、参考整理与提交 | ✅ |

本机检查：torch 2.2.2、NumPy 1.26.4、imageio-ffmpeg 0.6.0 可导入。未新装依赖、未创建训练代码或运行模型。本课先使用可控合成视频及示范控制器产生的模拟动作，不承诺真实机器人策略能力或真实数据集评估；LeRobot 等真实数据格式可后续扩展，不提前声称已使用。

## 第 1 步 · 输入与监督目标

场景为二维移动方块，便于看懂观测与示范动作配对。一个样本输入连续 3 帧；标签是示范脚本在窗口末端之后施加的下一个模拟水平移动量，例如 +2 / −2 像素每采样间隔，坐标向右为正。不是模型自动发现正确动作，也不把未来帧混入模型输入；实际机器人标签需来自对齐的示范动作 / 控制记录。

例子：过去 3 帧方块横坐标 10、12、14，示范控制器下一步继续右移 2 像素，标签 +2；过去 3 帧 14、12、10，下一步继续左移 2 像素，标签 −2。此类持续运动是简化的时序动作模仿 / 预测练习，不覆盖任务目标、接触动力学或真实闭环控制。后续数据生成需记录标签来源、实际时间间隔，避免把合成恒速规则当一般机器人动作规律。

训练流程：视频解码 → 连续三帧组成样本 → 小模型预测动作 → 与示范标签比较形成 loss → 反向传播与优化器更新参数；之后评估和持久化 checkpoint。视频不是直接以压缩字节送入普通小模型。

检查题（待回答）：如果只看到方块停留在某个位置的一张画面，能否确定它此前向左还是向右运动？为什么连续几帧能提供单帧没有的信息？确认本段无疑问后再写数据生成与读取代码。

> 我的回答：不能，需要连续帧来判断运动趋势。
> 点评：正确，在本例没有额外方向线索时，单帧只能提供位置 / 外观，连续帧提供位置随时间的变化。运动趋势也不等于任意真实任务的下一步正确动作；本实验的标签仍由已知示范控制器记录，限定为持续运动练习。当前停在第 1 步检查题，确认有无疑问后进入数据代码。

用户确认第 1 步无疑问，进入数据实操。

## 第 2 步 · 编码视频与动作数据（已运行，讲解进行中）

新增 `backend/scratch/robot_video_data.py` 和对应 `backend/tests/test_robot_video_data.py`，生成媒体与清单位于忽略的 `backend/scratch/robot-video-lab/training-demo/`。不覆盖同名数据。当前没有模型与参数更新，不把数据准备说成已训练。

### 2A：make_fixture 如何产生一组示范

16 个独立 episode，各是一段 32×32 RGB、8 帧、8 fps 的 MKV / FFV1 无损视频。方块为 4×4 像素，每段采用固定水平动作，四种动作 −2、−1、+1、+2 均衡分布；初始位置随机且保证不越界。时间戳间隔 1/8 秒，标签单位是每采样间隔的水平像素位移，不是速度 m/s 或电机命令。

每生成一帧，示范控制器先记动作，再移动到下一时刻。8 帧对应 7 个已记录帧间动作；最后一帧后不再记录动作。manifest.json 包含 episode / 视频 / split、时间戳和动作，以及供核查使用的位置。位置元数据不作为模型输入，动作标签也不能混入输入。

实测 episode-000：方块左上角 x 为 16、14、12、10、8、6、4、2，y=21；时间 0、0.125、…、0.875 秒，7 个动作均为 −2。视频名义播放时长 1 秒，最后一帧显示至片尾，不表示额外记录了末帧之后的动作。前 12 episode 训练，最后 4 验证，再在各自内部构建窗口，不跨 episode 或 split。

### 2B：decode_rgb 与 VideoActionDataset

decode_rgb 实际调用 FFmpeg 解码为 RGB 字节，按高 / 宽 / 通道重建 uint8 数组；Dataset 验证帧数、尺寸、帧率、动作数与严格递增时间戳。此处一次解码并在内存缓存所选 split，适合小规模教学；不是 L09 的每次取样读取，也不用于测生产吞吐。

关键转换：

```python
tensor = torch.from_numpy(arrays).permute(0, 3, 1, 2).float().div_(255)
```

把 [帧,高,宽,通道] 改为 [帧,通道,高,宽]，再转 float32 与 [0,1] 像素。getitem 返回窗口图像副本，避免调用者原地修改污染缓存；同时返回 action、episode_id、frame_indices、timestamps_s 和 action_interval_s 供核查。后续模型只接收 images，元数据不作为隐藏捷径输入。

### 2C：为什么一段是 5 个三帧窗口

| 输入帧 | 输入最后时刻 | 目标动作对应区间 |
|---|---:|---|
| 0,1,2 | 0.250 秒 | 帧 2 → 3，即 0.250～0.375 秒 |
| 1,2,3 | 0.375 秒 | 帧 3 → 4 |
| 2,3,4 | 0.500 秒 | 帧 4 → 5 |
| 3,4,5 | 0.625 秒 | 帧 5 → 6 |
| 4,5,6 | 0.750 秒 | 帧 6 → 7 |

窗口 5,6,7 虽有三帧，但缺少帧 7 之后的记录动作，故不作为监督样本。目标动作来自 actions[anchor]，不是把未来帧放入输入后猜动作。

运行前讲解数据生成、读取和窗口规则，然后执行：

```bash
backend/.venv/bin/python -m backend.scratch.robot_video_data \
  --output-dir backend/scratch/robot-video-lab/training-demo
```

实测正常退出：train 12 episode / 60 窗口，val 4 episode / 20 窗口。单样本 images=[3,3,32,32]，batch_size=8 的 images=[8,3,3,32,32]；action 单样本 [1]、batch [8,1]。第一条训练样本 episode-000 输入 0,1,2，时间 0,0.125,0.25，action=[−2]，区间 [0.25,0.375]。第一条验证样本为 episode-012，属于不同 episode。

9 项新测试通过：真实像素运动与标签对应、窗口 / 动作时间区间、split 隔离和动作覆盖、batch、缓存副本、元数据错误、拒绝覆盖与真实 CLI。首次沙箱内 CLI 因 OpenMP Can't open SHM 失败，经获准在沙箱外完整重跑 9 passed，没有跳过测试。完整 `cd backend && .venv/bin/python -m pytest -q tests scratch` 正常退出：249 passed，113.33 秒，1 项已有弃用警告。差异格式与项目 Stop hook 检查通过。

检查题（待回答）：为什么输入三帧 [0,1,2] 时，帧 3 不能也放入模型输入，而只能用与下一步有关的示范记录作为监督目标？点评并确认无疑问后，再讲小模型和训练循环。

### 用户补充：视频是否与传感器数据对应

用户在本停点询问本课是否结合传感器数据。明确当前实现只有视频窗口与示范动作对齐，positions_xy 目前仅用于核查，不是已实现的模型传感器输入。后续本课增加“视频 + 模拟本体状态”数据与小模型融合，不能把计划说成已运行。

教学采用同一模拟脚本记录的二维位置作为简化本体状态，标注为模拟传感器而非真实采集，先使用与帧相同的 8 Hz 时间轴；模型在窗口末端时刻 t 使用过去三帧与 t 的状态，目标为 t 到下一时刻的动作，不使用未来状态。增加状态字段时明确单位、归一化与输入契约，配对应测试；模型训练和 checkpoint 实现随后覆盖融合模型。真实系统的关节角 / 速度 / 力矩等可类比理解，但不同频率、时钟同步、噪声与缺失值不假装已由本玩具数据解决。

现有 249 passed 仅对应添加状态输入之前的数据实现，后续修改需重新验证。当前先解释动作标签与传感器状态角色区别，确认疑问后再改代码。

用户要求继续，开始增加模拟状态，不再重复前一检查题。

### 2D：视频窗口与当前模拟本体状态（已实现、已运行）

make_fixture 格式升为 schema_version=2，明确 state_source 为模拟控制器位置，不是真实传感器；positions_xy 的单位是方块左上角像素坐标，state_timestamps_s 明确逐条记录时间。原 schema 1 的 training-demo 不覆盖，也不静默当作已支持状态；新目录为 training-demo-state，生成目录以 training-demo*/ 忽略。

Dataset 检查模拟状态时间与视频时间逐条一致、位置为帧数×2的有限坐标且位于图像范围，然后对每个 anchor 只取 positions_xy[anchor] 与同一时刻的 state_timestamps_s[anchor]。本阶段只处理同频同钟，不把异步传感器按索引强行对齐。

运行前解释新增字段：

```python
state_xy = positions[anchor]  # 窗口末端的当前状态
state = state_xy / 31         # 32×32 坐标轴为 0～31，归一化到 0～1
state_time_s = timestamps[anchor]
```

实际代码使用 state_scale=[宽−1,高−1] 分轴归一化，以上是本数据的简写。state_xy 是 raw 像素坐标，state 是后续模型输入，时间字段用于检查；不能把归一化值误读成米，也不把动作 −2 再当作归一化坐标。

```bash
backend/.venv/bin/python -m backend.scratch.robot_video_data \
  --output-dir backend/scratch/robot-video-lab/training-demo-state
```

实测正常退出：仍为训练 60、验证 20 窗口；第一条训练 images 是 0、0.125、0.25 秒的帧，state_xy=[12,21]，state≈[0.38709676,0.67741936]，state_time_s=0.25；标签 −2 对应随后 0.25～0.375 秒。第一条验证状态 [20,18] 来自 episode-012，不与训练 episode 共用。单样本 images=[3,3,32,32]、state=[2]、action=[1]，batch_size=8 后分别为 [8,3,3,32,32]、[8,2]、[8,1]。

后续模型明确接受 images 和 state；state_xy / 时间戳是核查信息，不混入未来位置或目标动作。示范动作标签来自控制记录，状态是当时的自身情况，两者角色不同。单一恒速玩具任务不证明模型掌握真实机器人规划或传感器融合鲁棒性。

对应数据测试 14 passed，新增检查当前状态与实际解码末帧位置一致、归一化 / batch 形状、未来状态不影响当前输入、错时和缺失 / 非有限状态拒绝、旧版本拒绝。完整 `tests scratch` 回归正常退出：254 passed，115.65 秒，1 项已有弃用警告；差异格式与 Stop hook 检查通过。

检查题（待回答）：若在 0.25 秒预测下一步动作，却把 0.375 秒的位置也作为“当前状态”输入，会有什么问题？确认这段无疑问后进入小模型与训练代码，本段尚未训练。

> 我的回答：预测的帧作为输入了。
> 点评：抓住了未来信息泄漏。精确说，本题泄漏的是 0.375 秒的未来位置状态，不一定是那一帧图像；模型任务仍是预测动作而非生成未来视频帧。给定未来位置可能直接泄露动作结果，而真实推理时只有截至 0.25 秒的信息，不能获得它。当前停在状态对齐检查题，确认无疑问后进入融合小模型与训练代码。

### 代码细读：按函数逐个讲解（当前进行中）

用户要求先详细解释已写代码，且一个函数一个函数讲。暂停推进模型；顺序为 make_fixture → decode_rgb → VideoActionDataset 的 __init__ / __len__ / __getitem__ → main，每个函数讲完先确认疑问，不在同一轮跨到下一个函数。

第一轮 make_fixture：用途是生成视频与动作 / 模拟状态清单并返回 manifest.json 路径，不训练模型。解释关键字专用参数 episodes / seed、episode 数校验、文件命名和拒绝覆盖、固定随机种子、动作循环、初始坐标边界、8 帧数组与 4×4 白块、7 个帧间动作、FFmpeg stdin 无损编码、episode 划分、同钟时间戳及清单保存。横坐标始终限于 2～26，shift=7×dx，起点范围 [2−min(0,shift),26−max(0,shift)]，rng.integers 上界不包含所以写 27；dx=+2 时起点 2～12，dx=−2 时 16～26。当前停在 make_fixture 讲解，确认有无问题后才解释 decode_rgb。

用户追问 np.random.default_rng(seed)，解释生成器、种子和随机序列：新生成器相同种子和调用顺序产生相同序列，同一生成器连续调用会推进序列，不是永远取同一个数；integers 上界不含。用户确认无疑问，继续 decode_rgb。

第二轮 decode_rgb：imageio_ffmpeg.read_frames 返回逐项迭代读取对象，第一项为元信息，后续为 RGB 字节。next(reader) 取元信息，metadata["size"] 顺序为宽 / 高；逐帧 np.frombuffer 按 uint8 解释字节、reshape(height,width,3) 恢复像素维度、copy 获得独立数组；for 收集后 np.stack 增加帧维。finally 关闭 reader 并清理 FFmpeg 读取资源，异常也执行；无帧则明确失败。最终返回 [帧,高,宽,通道] 的 uint8 数组和元信息，还未变为 PyTorch 张量或归一化。当前停在 decode_rgb，确认疑问后再讲 Dataset.__init__。

用户追问 reshape 是否必须及如何重排。解释当前 frombuffer 是一维，需在某处按约定恢复图像维度；reshape 不理解颜色，按默认顺序安排数值、最后一维最快变化，(1,2,3) 表示一组内两个三元组，不缩放 / 不改变数值。RGB 含义来自 FFmpeg 输出约定。用户确认无疑问。

第三轮 Dataset.__init__：创建 Dataset 对象时调用，读取清单校验版本和 split，建立 videos 缓存及 records 窗口索引，计算 state_scale；只解码所选 episode，核对元信息与动作 / 时间 / 状态，再转 FCHW float32 / 255 并缓存。窗口 anchor=2..6，记录输入帧索引、当前状态与下一步动作区间，不将未来图像加入输入，不复制所有重叠窗口图像。初始化结束即完成视频解码，是教学内存缓存版本，与 L09 的按取样延迟读取不同；这些结构一致性检查不等于解决真实异步传感器同步。当前只讲 __init__，确认疑问后再讲 __len__。

用户追问真实项目是否也将视频全量解码放内存。明确当前实现确实如此，仅因全部 16×8×32×32×3 个 float32 图像载荷约 1.5 MiB，便于隔离训练与恢复；不作为大规模生产方案。RGB uint8 的 1080p、30fps 视频解码 1 分钟约 11.2 GB，float32 同形状约 44.8 GB，均未计额外缓存 / batch，不能拿压缩文件大小判断解码内存。

真实大视频通常清单 / Dataset 保留元数据索引，按训练所需时间窗口定位，解码所需帧并做有限预取 / 缓存，消费后释放；视频解码器及其内部缓冲也需预算。压缩视频可能依赖参考帧，定位目标窗口常需从可用关键帧开始解码并丢弃前面的帧，不等于单帧随机访问免费。结合短片段 / 分片、访问局部性、worker 内解码器复用和有上限缓存，按实际瓶颈测量；离线解码帧能转移工作，但增加存储 / 生成开销。多 worker、预取 batch 与图像 dtype 都影响合计内存。此轮只解释生产边界，不把当前练习改为复杂生产加载器，仍停在 __init__ 答疑。

用户继续问能否每次加载 10 帧。说明 read_frames 本已逐帧产出，当前列表推导 / stack 才把全片收集；可改成有限缓冲，累计 10 帧立即处理并释放，最后不足 10 帧也处理。此为顺序分块，不保证视频随机位置可独立解码，不是把压缩文件每 10 帧简单切字节。缓冲计数限制不等于进程峰值只有 10 帧，解码器内部、stack / dtype 转换、预取及消费者仍有占用。

读取块的 10 帧与训练 batch 的 10 样本不同；若每样本 3 帧滑窗，块 0～9 与 10～19 间仍需覆盖 [8,9,10]、[9,10,11]，通常保留前块末尾两帧接到下一块，并保存全局时间索引 / 动作对应。顺序流内打乱与全局随机访问是另一层设计。本轮只演示读取思路，不修改当前全量缓存 Dataset，未宣称新增分块读取实测或测试。

用户确认分块读取答疑无问题，继续按函数讲解。第四轮 __len__：返回 len(self.records)，是可取样窗口数量，而非视频数 / 帧数；len(dataset) 触发此方法。本例训练 12 视频×5 窗口=60，验证 4×5=20。该方法不读取或解码视频，只查询已建好的列表长度。当前停在 __len__，确认疑问后再讲 __getitem__，不在同一轮跨函数。

用户确认 __len__ 无疑问。第五轮 __getitem__：dataset[index] 触发，index 是全体窗口样本编号，不是帧号；查 records 再查缓存视频，根据 frame_indices 的首尾用左闭右开切片取三帧，clone 防止原地操作污染重叠样本缓存。当前位置转 float32、按 state_scale 归一化；action 包一层列表使形状为 [1]。返回图像、状态、动作及核查元信息，各字段用适当 Tensor dtype 便于 DataLoader 组 batch。单样本 images [3,3,32,32]、state [2]、action [1]；未来动作是监督标签，不是模型输入，时间 / 原位置也不会因出现在字典里就自动送入模型。当前只讲 __getitem__，确认疑问后才讲 main。

用户追问 [3,3,32,32] 是不是输出数组。明确它是 Tensor 的形状而非四个内容值，实际有 9216 个 float32 像素通道数值；images[0,0,10,20] 对应第 0 帧红通道指定行列。用户确认清楚，继续 main。

第六轮 main：ArgumentParser 接收必填 --output-dir，torch.set_num_threads(1) 固定 CPU 算子线程，不是 DataLoader worker 数；make_fixture 生成新数据，依次构建 train / val Dataset，取 dataset[0] 与 DataLoader 的首个 batch，打印形状、时间、状态 / 动作对应。next(iter(loader)) 只读一批用于检查，不是完整训练。num_workers=0 在主进程加载，shuffle=False 便于核对，batch_size=8 默认拼接字典字段。__name__ 入口保护使模块作为命令运行时执行 main，导入做测试时不自动生成数据。当前停在 main 讲解，确认疑问后进入模型，不跨到新代码。

用户追问真正训练语句，明确本数据文件没有训练。说明完整链路为 model 预测 → loss → zero_grad → backward → optimizer.step，其中 step 更新参数。用户确认清楚，数据代码细读完成。

## 第 3 步 · 小模型与训练代码（进行中）

### 3A：先读拟采用模型的 __init__

仍按一轮一个函数讲解。为降低基础门槛，先用固定 32×32 / 三帧 RGB 的小 MLP：视频张量按样本展平 9216 元素，Linear(9216,32) / ReLU 得到 32 维特征，与 2 维当前模拟状态拼接，再经 Linear(34,16) / ReLU / Linear(16,1) 预测下一步水平动作。保留时间 / 位置 / 任务边界，不声称小 MLP 是生产视频模型结构或必然泛化良好；后续实测训练 / 验证结果，不预设准确率。

```python
class VideoStateModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.video_encoder = nn.Sequential(
            nn.Flatten(start_dim=1),
            nn.Linear(3 * 3 * 32 * 32, 32),
            nn.ReLU(),
        )
        self.action_head = nn.Sequential(
            nn.Linear(32 + 2, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
        )
```

解释 nn.Module / super 的初始化与子层注册、Flatten 保留 batch、Linear 可学习权重 / 偏置及 ReLU 非线性。__init__ 定义结构并初始化参数，不运行训练也不加载现有 batch。此处仅讲义中展示拟实现结构，尚未新增模型 Python 模块 / 运行前向或优化；确认无疑问后再读 forward，模型代码与对应测试在执行前补齐。当前 254 passed 仅指已有数据实现，不冒充新模型验证。

用户追问 [8,9216] 的 8，说明第 0 维为 batch size=8，每行是一个三帧样本、每样本 9216 个图像数；Flatten(start_dim=1) 保留样本维，不混合样本。用户确认清楚并要求继续（2026-11-09）。

### 3B：forward 将两种输入接起来（代码预讲）

```python
def forward(self, images, state):
    video_features = self.video_encoder(images)
    features = torch.cat([video_features, state], dim=1)
    return self.action_head(features)
```

images=[B,3,3,32,32]，state=[B,2]，第一步编码为 video_features=[B,32]。cat 的 dim=1 沿特征维拼接为 [B,34]，每行保持同一样本的视频与状态，不沿 batch 维混样本。动作头输出 [B,1]，每个值是模拟水平位移预测，不是概率。用 model(images,state) 通过 nn.Module 调用 forward；__init__ 定义层，forward 指定实际数据流。

本轮只讲这一个函数；前向计算不等于参数更新，后续还需标签、loss、backward 与 optimizer.step。此段代码尚未写入模型模块或实际执行，不将形状推导当作训练结果；确认疑问后落实模型 / 测试和前向验证，再逐函数讲训练过程。

用户确认 forward 无疑问，落实模型并运行前向验证。

### 3C：第一次实际前向预测（已执行，未训练）

新增 `backend/scratch/robot_video_model.py`，结构与已讲解一致；forward 补充固定输入契约检查：images=[B,3,3,32,32]、state=[B,2] 且均 float32，避免错误形状静默进入网络。对应 `backend/tests/test_robot_video_model.py` 9 项通过，包含 batch 轴、整批 / 单样本一致、两输入梯度路径且不发生参数更新、错误形状和类型拒绝。测试中的 backward 仅验证可求导，不执行 optimizer.step，也不是完成训练。

实际读取 training-demo-state 的训练集首批，torch.manual_seed(42)、单 CPU 线程，构建 VideoStateModel，model.eval() 后在 torch.no_grad() 下做前向；eval 切换模块模式，no_grad 不记录本次梯度。模型此时为初始化参数，未用动作标签更新。执行成功：images=[8,3,3,32,32]、state=[8,2]、prediction=[8,1]，全部有限值。

首四条均来自 episode-000，不是对整个数据集的质量统计：

| 输入窗口末端 | 初始化预测动作 | 示范标签 |
|---:|---:|---:|
| 帧 2 | 0.06730703 | −2 |
| 帧 3 | 0.05598761 | −2 |
| 帧 4 | 0.06058995 | −2 |
| 帧 5 | 0.08826137 | −2 |

输入路径与输出形状已跑通，不代表模型已学会运动；下一段需定义 loss 并逐函数讲参数更新。完整 `tests scratch` 回归正常退出：263 passed，123.81 秒，1 项已有弃用警告；差异格式和 Stop hook 检查通过。本轮尚未实现训练函数与 checkpoint，确认用户疑问后继续。

用户要求继续，进入损失计算，仍先讲一个操作，不提前执行训练更新。

### 3D：nn.MSELoss 的含义与计算（已演示）

连续动作预测使用均方误差：每个预测减标签、平方，再对所有元素取平均。loss_fn=nn.MSELoss() 创建可调用对象；loss=loss_fn(prediction,batch["action"]) 得到单个 Tensor 标量。两者应保持同为 [B,1]，避免 [B] 与 [B,1] 发生广播造成错误比较。对本玩具数据 MSE 单位为像素位移平方，不是准确率。

运行前解释预测 / 标签平方误差后，用两条人工数值演示：prediction=[[-1],[1]]、target=[[-2],[2]]，误差为 +1、−1，平方均为 1，实际 PyTorch 输出 MSE=1.0。此是独立数值演示，不是前述真实模型训练或质量结果。平方防止正负误差相互抵消，并放大较大误差；相同标签条件下更小表示更贴近这些标签，不保证未见数据或真实任务更好。

本轮没有新增模型 / 训练 Python 模块，没有调用 backward 或 optimizer.step，没有进行参数更新。确认损失概念无疑问后再讲一次训练更新函数。

用户追问如何知道某步参数实际应该是多少、loss 中“实际值”从何而来。暂停更新函数，澄清模型内部权重 / 偏置没有预先给定的正确答案；监督学习已知的是样本标签，即示范控制器在对应观测之后记录的动作。当前 make_fixture 的 actions.append(float(dx)) 保存脚本示范命令，训练读取此标签而非模型自己生成“真值”。以 episode-000 为例，输入三帧与当前状态，标签 −2 已在 manifest 中记录；prediction 可为 0.0673，loss 比较两动作而非比较权重与某份正确权重表。

真实数据标签可来自遥操作 / 专家控制器的对齐指令记录，须区分指令与实际测得的执行结果，按任务定义目标，并确保示范质量。记录过的动作不自动等于最优动作，失败数据也不自动带正确示范；无可信标签则不能直接做此种监督动作损失。训练通过反向传播计算现有参数对误差的影响，再由优化器更新，不需要事先知道最优参数，训练时标签仅用于比较而非模型输入。当前停在监督标签来源答疑，确认无疑问后再继续。

用户确认标签来源无疑问，要求继续，开始单 batch 实际训练。

### 3E：train_step 的第一次实际参数更新

新增 `backend/scratch/robot_video_train.py`，本阶段只提供一个训练函数，不提前跨到 epoch / checkpoint。运行前逐项解释：

```python
def train_step(model, optimizer, batch):
    model.train()
    optimizer.zero_grad(set_to_none=True)
    prediction = model(batch["images"], batch["state"])
    loss = nn.MSELoss()(prediction, batch["action"])
    loss.backward()
    optimizer.step()
    return loss.detach().item()
```

实际实现另校验预测 / 标签同形同类型，拒绝非有限 loss 后才更新，避免 [B,1] / [B] 广播和 NaN 损坏参数。model.train 只切模式，zero_grad 清梯度不清权重；backward 求参数梯度，step 才修改参数。Adam 持有 model.parameters 引用，lr=0.001 为本例学习率；无需返回整个模型。返回值对应更新前前向的 MSE，更新后误差需要重新前向。

新测试 5 passed：真实视频 batch 确实更新参数、相同 batch 误差下降且 Adam 计数 1、旧梯度被清除、标签错误 / 非有限损失不修改参数。随后实际读取 training-demo-state 首批 8 样本，固定 torch.manual_seed(42)、单 CPU 线程，创建新模型与 Adam，执行一次 train_step。前后均在无梯度模式重新测同批 MSE：

| 项目 | 实测结果 |
|---|---:|
| 更新前 batch MSE | 3.12264156 |
| train_step 返回值 | 3.12264156 |
| 更新后同 batch MSE | 2.91468239 |
| 第一条预测，更新前 | 0.06730703 |
| 第一条预测，更新后 | 0.00150895 |
| 第一条示范标签 | −2 |
| Adam 更新计数 | 1 |

已明确比较参数前后，确认至少一部分权重变化；训练不再只停留于形状 / 加载。一次更新仅对当前 batch 验证，不能推断验证集质量或每步 loss 必然下降。这次演示模型仅在进程内，未保存，不能把下一个新进程当作自动保留该进度；checkpoint 随后才实现。完整 `tests scratch` 回归正常退出：268 passed，115.19 秒，1 项已有弃用警告；差异格式及 Stop hook 检查通过。

当前停在单步更新讲解与结果，确认有无问题后再讲整轮训练与独立验证，不提前执行完整训练。

用户追问 MSE 含义，重新解释 Mean Squared Error / 均方误差：预测减标签、平方再平均，例 −1 对 −2、0 对 2，平方 1 与 4，MSE=2.5；不是百分数或错误率。用户确认无疑问，继续整轮训练。

### 3F：train_epoch 遍历所有 batch（已执行一轮）

新增同文件 train_epoch 函数，本轮只讲这一个函数：

```python
def train_epoch(model, optimizer, loader):
    weighted_loss = 0.0
    samples = steps = 0
    for batch in loader:
        count = batch["action"].shape[0]
        loss = train_step(model, optimizer, batch)
        weighted_loss += loss * count
        samples += count
        steps += 1
    return {"train_mse": weighted_loss / samples,
            "samples": samples, "steps": steps}
```

实际实现另拒绝空 batch / 空数据，避免把没有训练误报为零误差。一次遍历数据集称一轮 / epoch，60 样本 batch_size=8 且不丢尾批，形成 7×8+4 共 8 批，参数更新 8 次。函数复用外部传入的模型与优化器，不在每批或每轮重置 Adam。

每批 train_step 返回的是该批平均 MSE，累计时乘本批样本数、最后除总样本数，避免末批只有 4 样本却按 8 样本等权计算。报告来自各批次更新前预测的轨迹，期间参数持续改变，不等同于最终模型对完整训练集重新评估的损失。数据集遍历、优化器 step 和模型层的 forward 是不同计数层级。

新增 3 项测试覆盖末批加权（8 样本误差 1 与 4 样本误差 4，整体平均为 2 而非 2.5）、真实视频一轮 20 样本 3 批且跨轮 Adam 计数 3→6、空数据拒绝；训练模块合计 8 passed。随后固定 torch.manual_seed(42)、DataLoader 独立 generator seed=43，shuffle=True / num_workers=0 / batch=8，用新模型和 Adam lr=0.001 实际训练一整轮。结果 train_mse=2.39807402，samples=60，steps=8，Adam 计数 8，正常退出。

本次只运行一轮，无验证、无 checkpoint，演示参数仅在进程内。数值不能与不同 batch 顺序 / 计时边界的其他 loss 直接当同一质量曲线比较。完整 `tests scratch` 回归正常退出：271 passed，114.82 秒，1 项已有弃用警告；差异格式及 Stop hook 检查通过。确认有无问题后再讲独立评估函数，并最终运行多轮训练。

用户确认整轮训练讲解无疑问，进入独立评估。

### 3G：evaluate 固定参数检查验证数据（已执行）

本轮只新增并讲 evaluate：输入模型和 loader，不接受 optimizer、不调用 backward / step。

```python
@torch.no_grad()
def evaluate(model, loader):
    was_training = model.training
    model.eval()
    weighted_loss = 0.0
    samples = 0
    try:
        for batch in loader:
            prediction = model(batch["images"], batch["state"])
            loss = nn.MSELoss()(prediction, batch["action"])
            count = batch["action"].shape[0]
            weighted_loss += loss.item() * count
            samples += count
    finally:
        model.train(was_training)
    return {"mse": weighted_loss / samples, "samples": samples}
```

实际实现另外校验目标同形同类型、有限损失与非空评估集。eval 切换模块模式，no_grad 关闭本函数梯度记录，两者目的不同；finally 恢复之前模式，即使异常也执行。每个 batch 使用相同固定模型，按样本数加权后是该模型在完整指定数据集上的 MSE，区别于训练轨迹上不断变化参数的累计 loss。

验证集也有示范标签，用来算误差，但本函数不据此更新权重。按 episode 已划分的验证 4 段 / 20 样本；真实建模中的模型选择仍可能间接使用验证结果，不能将其称为永远不受决策影响的最终测试集。

新增 5 项测试：参数与已有梯度不变、训练 / 评估模式恢复（两种模式分别验证）、末批加权与无梯度记录、空集和错误标签拒绝并恢复模式。训练模块合计 13 passed。实际重新创建相同 seed=42 模型与 Adam，训练 shuffle generator=43、验证 loader generator=44（不打乱），先验证、训练一轮、再验证：

| 项目 | MSE | 样本 / 更新 |
|---|---:|---|
| 未训练模型验证 | 2.56242342 | 20 样本，无更新 |
| 本轮训练轨迹累计 | 2.39807402 | 60 样本，8 更新 |
| 一轮后模型验证 | 2.83817949 | 20 样本，无更新 |

Adam 计数保持 8，验证没有额外 step。验证误差本次上升，不宣称训练带来泛化改善；训练轨迹 loss 与验证 loss 的数据、参数时点不同，不能直接相减当提升。单轮小数据结果不足以断言已过拟合或某个原因，后续观察多轮趋势；更多训练也不保证一定改善。模型仍未保存，完整 `tests scratch` 回归正常退出：276 passed，117.51 秒，1 项已有弃用警告；差异格式和 Stop hook 检查通过。

当前停在评估函数与实际结果，确认理解后再进入多轮训练，不为得到好看数值私自修改验证划分。

用户确认评估无疑问，进入多轮训练。

## 第 4 步 · 多轮曲线与泛化（已实际训练，讲解进行中）

### 4A：fit 串联整轮训练与验证

新增 fit(model,optimizer,train_loader,val_loader,epochs=30)，运行前解释：先 evaluate 记录第 0 轮未训练模型；for epoch in range(1,epochs+1) 中先 train_epoch、再 evaluate，并将指标放入 history。循环内不重新创建模型 / Adam。30 轮加初始记录共 31 项，60 个独立训练窗口重复呈现 30 次，不是新增 1800 个独立样本；每轮 8 更新，共 240 次。

```python
baseline = evaluate(model, val_loader)
# 第 0 轮只有验证值，train_mse=None。
for epoch in range(1, epochs + 1):
    training = train_epoch(model, optimizer, train_loader)
    validation = evaluate(model, val_loader)
    history.append(...)
```

新测试 3 项验证基线 / 轮次记录、跨轮优化器状态持续、无效轮数拒绝；训练模块 16 passed。随后使用相同 schema 2 数据、torch seed=42、训练 loader seed=43 / 验证 seed=44、batch=8、单 CPU 线程、Adam lr=0.001，实际执行 30 轮，未调整验证划分或模型以制造改善。

### 4B：本次真实结果不能称质量达标

| 轮次 | 训练轨迹平均 MSE | 固定模型验证 MSE |
|---:|---:|---:|
| 0 | 未训练 | 2.56242342 |
| 1 | 2.39807402 | 2.83817949 |
| 2 | 1.86274817 | 3.29812737 |
| 5 | 0.65248266 | 4.34474030 |
| 10 | 0.08758494 | 4.19172535 |
| 15 | 0.02587314 | 4.02015419 |
| 20 | 0.00973425 | 3.89067202 |
| 25 | 0.00276168 | 3.86565065 |
| 30 | 0.00080844 | 3.83733349 |

每个训练轮都实测 samples=60、steps=8，Adam 计数为 240。训练轨迹损失很低但独立验证误差持续较高，呈明显过拟合 / 泛化不足迹象；训练轨迹与固定模型整集误差本来有计量差别，不能将两者当完全同一时点，但本例仍不能声称未见数据表现改善。观察范围内最佳验证值是第 0 轮，不应只挑训练后某个低点而忽略未训练基线。fit 返回末轮模型，不自动恢复最佳版本。

小数据、模型结构 / 容量和分布覆盖等需进一步诊断，当前曲线不单独证明哪一个具体原因；多加训练轮数不保证改善，也不能拿验证集混入训练来修饰结果。需要质量改进时应明确新的对照方案，仍保留独立划分。checkpoint 技术演练随后进行，不意味着该模型已可部署真实机器人。

history-30epochs.json 保存在 training-demo-state 的忽略目录，含种子、学习率、数据清单 SHA256 和完整曲线，不是参数 checkpoint。计时 fit_wall_s≈0.334 秒仅覆盖小数据缓存后这次训练 / 验证调用，不含之前的视频生成 / 解码，不能当生产端到端性能。演示参数未保存，进程结束后不能从这份 JSON 直接续训。完整 `tests scratch` 回归正常退出：279 passed，117.28 秒，1 项已有弃用警告；差异格式与 Stop hook 检查通过。

检查题（待回答）：本例训练损失接近 0，能否宣布模型已经学会了能推广到新 episode 的动作规律？应结合哪一列判断？先点评并确认疑问，再进入泛化讨论或 checkpoint，不直接把失败结果表述为成功模型。

> 我的回答：不能，这有可能和训练数据有关，还要看验证的结果。
> 点评：正确，应结合独立验证结果，训练数据数量 / 覆盖可能是原因；模型容量与结构、训练配置等也可能影响，当前曲线不能单独锁定根因。后续质量改进需有对照且维持独立划分，不能把“验证差”归咎为验证无用。当前先确认有无疑问，之后进入 checkpoint 保存与恢复，后者验证进度恢复技术，不意味着该模型质量已达标。

用户确认泛化讨论无疑问，进入 checkpoint 实操。

## 第 5 步 · 保存与恢复（进行中）

### 5A：save_checkpoint 在整轮边界保存完整进度（已执行）

新增 `backend/scratch/robot_video_checkpoint.py`，本轮只讲并执行 save_checkpoint，未实现 load / resume。约束为单 CPU 进程、num_workers=0、完成整轮且参数更新已结束，没有梯度累积中途状态或在途预取；不能直接推广为分布式 / GPU 保存协议。

运行前解释主要 payload：

| 字段 | 内容 / 作用 |
|---|---|
| model | model.state_dict()，权重和持久 buffer；本模型没有需另处理的随机层状态 |
| optimizer | optimizer.state_dict()，Adam 的 m / v、更新步数及参数组设置 |
| completed_epoch / global_step | 已完成轮数和更新数，恢复应从下一轮继续 |
| config | 小模型版本、学习率、batch、CPU 线程等配置 |
| manifest_sha256 | 数据清单字节指纹，恢复前核验声明的数据版本 |
| rng | Python / NumPy 全局 RNG、PyTorch CPU RNG、显式训练 / 验证 loader generator 状态 |

本轮无梯度累积、每步下次先清梯度，因此不保存 p.grad；模型内部最佳权重没有已知答案，只保存当前实际学到的值。NumPy default_rng 等额外自建生成器或 CUDA RNG 不会被这些字段自动全部覆盖；当前 fixture 生成后固定、训练不使用其他此类生成器。清单指纹也不是对所有实际视频内容的逐文件完整证明，源数据引用 / 保留与代码配置仍需明确。

文件先使用 NamedTemporaryFile 在同一目录写入，torch.save 后 flush / fsync，再 os.replace 发布正式版本；异常清理临时文件，已有正式文件拒绝覆盖。单写者假设下避免半文件冒充完成版本，不声称可抵御所有断电 / 存储故障，也不包含多写者竞争协议。硬杀可能留下未发布临时文件，后续按明确正式路径加载。

新测试 5 passed：模型和 Adam 内容 / 进度及 RNG 状态正确、保存不推进相关 RNG、已有版本不覆盖、写入故障不发布残缺文件并清理、负进度拒绝。随后使用相同 seed=42 / loader seed43,44 / Adam lr=0.001 / batch8，从新模型训练 5 轮，再保存：

```python
save_checkpoint(
    path, model, optimizer,
    completed_epoch=5, global_step=40,
    manifest_path=manifest, config=config,
    train_generator=train_loader.generator,
    val_generator=val_loader.generator,
)
```

实际产物 `backend/scratch/robot-video-lab/training-demo-state/epoch-005.pt`，3577541 Byte，读取本轮刚生成文件验证 completed_epoch=5、global_step=40、Adam 各参数更新计数40，包含全部 5 类 RNG 字段。该轮验证 MSE≈4.3447，保存进度不代表质量合格，也不是宣称选到了最佳模型。文件在生成目录忽略，不提交二进制；保存 / 恢复代码及测试将提交。读取 payload 检查内容不等于已完成恢复训练。

本次进程退出时进度已在正式 checkpoint，而非仅 history JSON。下一段才写 load_checkpoint 并验证恢复模型 / 优化器与数据顺序。完整 `tests scratch` 回归正常退出：284 passed，117.08 秒，1 项已有弃用警告；差异格式和 Stop hook 检查通过。先确认保存函数有无疑问，不提前跨到恢复函数。

用户确认保存无疑问，进入恢复函数。

### 5B：load_checkpoint 在新进程恢复（已执行，未续训）

本轮只讲 load_checkpoint：先读取本课刚生成的可信本地 checkpoint（含 NumPy RNG，显式 torch.load(weights_only=False,map_location="cpu")），检查格式 / 必需字段、与当前任务的配置和清单指纹、非负进度、必要 RNG 以及模型键 / 形状 / dtype。数据与配置不匹配等常见情况在修改当前模型前拒绝。不是任意损坏文件所有字段的事务回滚协议。

```python
model.load_state_dict(payload["model"], strict=True)
optimizer.load_state_dict(payload["optimizer"])
random.setstate(rng["python"])
np.random.set_state(rng["numpy"])
torch.set_rng_state(rng["torch"])
train_generator.set_state(rng["train_loader"])
val_generator.set_state(rng["val_loader"])
```

模型结构仍需代码先创建；load_state_dict 把保存权重装进同结构实例。优化器先关联该实例参数，再加载 Adam 状态与参数组（包括原学习率）。所有创建 / 加载完成后再恢复 RNG，避免模型初始化消耗已恢复序列。返回 completed_epoch、global_step、config 和 optimizer_restored 标志，调用者从 completed_epoch+1 开始。

函数提供 restore_optimizer=False 供下一段受控比较：保留同权重、数据与 RNG，刻意不给新 Adam 恢复 m/v 等，从而隔离优化器状态影响。本次使用默认 True 完整恢复；关闭这个开关并不表示执行了完整续训恢复，也不把含元数据和 RNG 的受控对照误称为字面上只读取权重文件。

checkpoint 模块现 12 passed，新增验证权重 / Adam / 五类随机流恢复，后续随机数与样本排列相同，加载可还原参数组学习率；数据 / 配置 / 格式 / 进度 / 模型形状不匹配在修改模型前拒绝，且支持受控跳过优化器。各测试隔离并还原全局 RNG，避免污染其他测试。

实际另起新进程，torch seed=999，创建新模型 / Adam / 训练与验证 loader（生成器先随意初始化为 999 / 1000），随后 load epoch-005.pt，使用同一明确配置和清单。输出：

| 项目 | 恢复结果 |
|---|---|
| completed_epoch | 5 |
| 下一训练轮 | 6 |
| global_step / Adam step | 40 / 40 |
| optimizer_restored | True |
| 验证 MSE | 4.344740295410157 |
| 保存时第 5 轮 MSE | 4.344740295410157 |

已精确核对恢复后预测质量与之前同一模型一致，不要求该质量合格。此次只加载与评估，未执行第 6 轮；验证会推进验证 loader 的生成器，后续公平续训对照会重新加载到共同边界，原文件不变。完整 `tests scratch` 回归已正常退出：291 passed，117.15 秒，1 项已有弃用警告；差异格式和 Stop hook 检查通过。

当前停在恢复函数答疑，确认无疑问后再运行完整续训与不恢复 Adam 的比较，不提前推进。

用户要求继续，进入实际跨进程续训对照。

### 5C：连续 10 轮 vs 5+5 完整恢复 vs 重置 Adam（已实测）

新增 `backend/scratch/robot_video_resume_demo.py`，只新增一个编排入口 main，内部串联已讲的 data / model / fit / train_epoch / evaluate / checkpoint 函数。运行前解释三种模式，并依次独立启动命令：

```bash
backend/.venv/bin/python -m backend.scratch.robot_video_resume_demo \
  --manifest backend/scratch/robot-video-lab/training-demo-state/manifest.json \
  --output-dir backend/scratch/robot-video-lab/training-demo-state/resume-comparison \
  --mode prepare
# 第二次命令保持路径不变，--mode resume。
# 第三次命令保持路径不变，--mode without-adam。
```

prepare 同进程内重设相同初始条件，分别跑连续 10 轮参考、5 轮后安全保存的中断点，再正常退出。reference-final.pt 和 interrupted-005.pt 都保存完整状态。后两个命令确实是新 Python 进程：先用 seed999 创建全新对象，再从同一中断点加载到第 5 轮；直接执行第 6～10 轮，不额外做一次基线验证以改变采样状态。

prepare 初始 Python / NumPy / torch seed 均42，训练 / 验证 loader 43 / 44；模型、数据、batch8、Adam lr0.001、单 CPU 线程一致。without-adam 加载相同权重、进度与全部 RNG，仅跳过 Adam 状态，保持学习率等其他设置一致，是优化器状态消融，不声称其文件只包含权重。固定验证划分不改。

| 项目 | 连续 10 轮 | 5+5 完整恢复 | 5+5 不恢复 Adam |
|---|---:|---:|---:|
| 总计完成轮数 | 10 | 10 | 10 |
| 总训练更新数 global_step | 80 | 80 | 80 |
| 最终 Adam 内部计数 | 80 | 80 | 40 |
| 恢复瞬间权重与中断点 | — | 完全相同 | 完全相同 |
| 最终权重与连续参考 | 本身 | 逐项完全相同 | 不同 |
| 最大参数绝对差 | 0 | 0 | 0.0293964632 |
| 第 10 轮验证 MSE | 4.19172535 | 4.19172535 | 4.34276066 |

完整恢复的模型、Adam 状态、五类 RNG、后 5 轮训练 / 验证记录都与连续参考严格一致；without-adam 的 RNG / 取样进度也相同，但 Adam 从新状态开始更新，因此后续参数路径不同。其内部计数40不是“只训练5轮”，而是前5轮的优化器历史丢失后只累计了后5轮。当前例中验证更差，不泛化成重置优化器必然降低质量；可作为有意新训练策略，但不属于精确续训。

这些逐位一致结论限定于本例 CPU / 单线程 / 固定数据 / 无随机增强和固定实现；GPU、跨硬件或分布式通常还需确定性与容差验证。当前退出发生在已保存的整轮边界，没有未保存进度；真实抢占若发生于后续未保存步，仍需重算那段工作，不因恢复正确而消失。

产物为 prepare.json、resume.json、without-adam.json、reference-final.pt、interrupted-005.pt、resumed-final.pt，全部在忽略实验目录。代码 / 测试入库，二进制和报告可重建。新增真实多进程集成测试通过，覆盖三阶段、参数 / 优化器 / RNG / 曲线一致、重置路径分歧与拒绝覆盖。完整 `tests scratch` 正常退出：292 passed，124.29 秒，1 项已有弃用警告；差异格式与 Stop hook 检查通过。

检查题（待回答）：不恢复 Adam 时，恢复瞬间的预测可以相同，为什么再训练后结果会不同？保存权重是否足以保证沿原更新过程继续？点评并确认无疑问后收束 checkpoint 并整理本课参考，不误称模型泛化问题已解决。

> 我的回答：梯度信息丢了。
> 点评：方向正确，准确说是 Adam 的历史梯度统计 m、梯度平方统计 v 和更新计数丢失；本批梯度仍会由 backward 重新计算，不是再也算不出梯度。本课整轮边界无梯度累积，不保存 p.grad 是有意设计。新 Adam 用相同当前梯度结合不同历史 / 计数，更新量可能不同，因此权重和后续梯度轨迹逐渐分歧。模型已经学到的权重仍保留，改变的是后续更新行为。当前确认这项补充是否有疑问，之后整理 L13 参考与提交；暂不提前宣布整课收尾完成。

用户确认最后补充无疑问，并要求用简单语言概括训练全流程，说明输入、实际训练操作、输出，配伪代码与函数名。以下作为本课收尾总结。

## 第 6 步 · 全流程复盘与最终记录

一句话：给模型过去的视频和当前状态，让它预测下一步动作；用已记录的示范动作计算误差，反复调整内部参数，再用独立数据检查效果，并保存可恢复的状态。

输入包括三类：过去三帧图像、与窗口末端对齐的当前模拟本体状态、示范动作标签。模型本身只接收前两类；标签来自示范脚本 / 真实场景的遥操作或专家控制记录，仅用于损失和评估，不作为模型输入。我们不预先知道最优权重，训练通过梯度和优化器寻找更符合示范数据的参数。

概念伪代码（把现有函数展开，实际 fit 当前不自动逐轮保存）：

```python
for epoch in range(1, epochs + 1):
    model.train()
    for batch in train_loader:
        optimizer.zero_grad()
        prediction = model(batch["images"], batch["state"])
        loss = MSE(prediction, batch["action"])
        loss.backward()
        optimizer.step()
    validation = evaluate(model, val_loader)
    if epoch % 5 == 0:
        save_checkpoint(...)  # 参数、Adam、进度和随机状态等
```

对应实现：make_fixture 生成演示数据，decode_rgb 解码，VideoActionDataset 构建时序输入 / 状态 / 标签；VideoStateModel.forward 预测；train_step 更新一个 batch；train_epoch 遍历一轮；evaluate 固定权重评估；fit 串联多轮；save_checkpoint / load_checkpoint 保存恢复；robot_video_resume_demo.main 编排跨进程对照。

训练主要产物是更新后的模型参数，另有验证结果、配置与日志。保存 checkpoint 后还可恢复 Adam 和进度；history JSON 不是参数文件。部署 / 推理只需同类型视频与状态产生动作预测，不需要提供示范标签，也不在普通前向中自动训练。

本课完成但不宣称模型质量合格：30 轮训练轨迹 MSE≈0.0008，验证 MSE≈3.8373，高于未训练基线≈2.5624。完整恢复在本例 CPU 条件下与连续训练权重 / Adam / RNG / 曲线一致，重置 Adam 则分歧，验证的是续训正确性，不是泛化已改善。

最近完整回归为 292 passed（124.29 秒，1 项已有弃用警告），此后只补课堂记录与参考，无新代码变更，不重复声称已再次测试。数据、模型、训练、保存 / 恢复、三进程演示代码和对应测试纳入提交；生成视频、报告和 checkpoint 按规则忽略；无关临时笔记改动保留。前文进行中 / 停点为历史教学状态，以此处最终记录为准。

参考：`../robot-data-reference.md` 第 16 节；口述与主要答疑：`../robot-data-interview-notes.md` 题 7。剩余一个必修实操专题：成本估算器。继续下一课前仍按约定确认有无问题。
