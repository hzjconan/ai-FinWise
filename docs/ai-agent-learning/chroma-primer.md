# Chroma 上手讲义（向量数据库怎么用）

> 工具类速查，配 `backend/scratch/s4_05_vector_db_chroma.py` 练习用。
> 一句话心智模型：**Chroma = 一张"会算相似度的表"**——你往里塞「一行 = id + 向量 + 原文 + 元数据」，
> 查询时给一个向量，它把最近的几行还给你。核心逻辑和你 s4_01 手搓的一模一样，它只是做到了**落盘 + 过滤 + 扛量**。

---

## 一、三层对象（理解这三层就够了）

```
Client（连接/库）
  └─ Collection（一张表，如 "finwise_products"）
        └─ 行：id(唯一字符串) + embedding(向量) + document(原文) + metadata(结构化字段)
```

- **Client**：连到一个 Chroma 存储。两种：
  - `chromadb.PersistentClient(path="...")` —— **落盘**，进程重启数据还在（生产/我们用这个）。
  - `chromadb.EphemeralClient()` —— 纯内存，进程一停就没（临时试）。
- **Collection**：一张表，按业务分（产品一张、合规一张…）。一个 Client 下可以有多张。
- **行**：四件套。查询时 `document` 和 `metadata` 会原样还给你（省得再回主库查）。

---

## 二、最小闭环（5 步，照着能跑）

用一个和练习**无关**的小例子（3 条动物笔记），把 5 步走一遍：

```python
import chromadb

# 1) 连库（落盘到某目录）
client = chromadb.PersistentClient(path="/tmp/demo_chroma")

# 2) 建/取一张表。★ 显式指定 cosine 空间（默认是 L2 欧氏，文本检索要 cosine）
col = client.get_or_create_collection(
    name="animals",                      # ★ 名字 3~512 字符、[a-zA-Z0-9._-]，"t" 这种会报错
    metadata={"hnsw:space": "cosine"},
)

# 3) 写入（这里向量先随便手写；真实场景是 encoder 编码出来的）
col.upsert(
    ids=["cat", "dog", "shark"],                       # 唯一字符串
    embeddings=[[1, 0, 0], [0.9, 0.1, 0], [0, 0, 1]],  # 每行一个向量（list，不是 numpy）
    documents=["猫，家养宠物", "狗，家养宠物", "鲨鱼，海洋掠食者"],  # 原文，检索时原样返回
    metadatas=[{"habitat": "home"}, {"habitat": "home"}, {"habitat": "sea"}],  # 结构化字段
)

# 4) 语义检索：给一个 query 向量，取最近的 k 行
res = col.query(query_embeddings=[[1, 0, 0]], n_results=2)

# 5) 元数据过滤 + 检索：只在 habitat=home 的行里找
res2 = col.query(query_embeddings=[[1, 0, 0]], n_results=2, where={"habitat": "home"})
```

---

## 三、逐个 API 讲清楚

### `upsert(...)` —— 写入（vs `add`）
- 收 **4 个等长的 list**：`ids` / `embeddings` / `documents` / `metadatas`。
- `upsert` = 有则更新、无则插入（**幂等**，脚本重复跑不报错）。`add` 遇到重复 id 会**报错**——所以练习/可重跑场景用 `upsert`。
- **`embeddings` 要 list**：numpy 数组先 `.tolist()`。
- `ids` 必须是**字符串**且唯一（用业务主键，如产品 code）。

### `query(...)` —— 检索
```python
res = col.query(query_embeddings=[qvec], n_results=k, where={...})
```
- 返回一个 **dict**，键有 `ids` / `distances` / `documents` / `metadatas` / `embeddings`…
- ⚠️ **每个值都是「list 套 list」，最容易在这里绕晕**。关键：**外层不是"第几条记录"，而是"第几条 query"**。因为 `query_embeddings=[...]` 收的是**一批** query（可一次查多条），返回必须**按 query 分组**。

  一次查 **2 条** query 时看得最清：
  ```python
  res = col.query(query_embeddings=[向量A, 向量B], n_results=2)
  res["ids"] == [
      ['cat', 'dog'],       # ← query A 的 top-2
      ['shark', 'whale'],   # ← query B 的 top-2
  ]                          # 外层=哪条 query，内层=那条 query 的 top-k 命中
  ```
  我们通常**只查 1 条**，外层长度就是 1，所以先取 `[0]` 把"单条 query 的批次"剥掉，才拿到 top-k 列表：
  ```python
  res["ids"]        # [['cat', 'dog']]      ← 还套着一层"按 query 分组"
  res["ids"][0]     # ['cat', 'dog']        ← query#0 的（全部）命中，不是"第一条记录"！
  res["ids"][0][0]  # 'cat'                 ← 要具体某条记录，得两层下标
  ```
- **两层下标各是什么**：
  ```
  res["ids"][ i ][ j ]
              │    └─ 第 j 个命中（0=最相关，个数由 n_results 决定）
              └────── 第 i 条 query（只查 1 条 → i 恒为 0）
  ```
- `distances` / `documents` / `metadatas` 是**同样的两层结构**，且**跨字段按下标对齐**（平行数组）：`ids[0][j]`、`distances[0][j]`、`metadatas[0][j]` 是**同一条命中**的 id / 距离 / 元数据。所以先 `[0]` 剥掉批次层、再 `zip` 逐条组装：
  ```python
  ids   = res["ids"][0]         # ['cat', 'dog']
  dists = res["distances"][0]   # [0.0, 0.05]
  metas = res["metadatas"][0]   # [{'habitat':'home'}, {'habitat':'home'}]
  for _id, dist, meta in zip(ids, dists, metas):   # 一一对应
      ...
  ```
- 一句话：**query 结果永远"按 query 分组"，单查也套一层——先 `[0]` 剥批次，再按下标取命中。**

### `where={...}` —— 元数据过滤（向量库的杀手锏）
- `where={"risk_level": "C3"}`：**先筛出满足条件的行，再在子集里算相似度**。手搓版做不到这个。
- 支持操作符：`{"risk_level": {"$in": ["C2","C3"]}}`、`{"$and": [...]}`、`{"price": {"$lte": 100}}` 等。
- 这就是"通用 agent 里先按域/条件缩范围、再语义检索"的落地件（呼应 Agentic RAG 那节）。

### 其它常用
- `col.count()` —— 行数（验证写入/持久化）。
- `client.get_collection("name")` —— 取已存在的表（不存在会抛错）。
- `client.delete_collection("name")` —— 删表。
- `col.get(ids=[...])` —— 按 id 直接取行（不算相似度）。
- `col.peek()` —— 瞄一眼前几行，调试用。

---

## 四、必须记的 4 个坑（都是真会绊你的）

| 坑 | 说明 | 对策 |
|---|---|---|
| **名字长度** | collection 名要 **3–512 字符**、只含 `[a-zA-Z0-9._-]` | 别用 `"t"` 这种，用 `"finwise_products"` |
| **distance 不是 similarity** | Chroma 返回**距离，越小越近**；不是"相似度越大越好" | cosine 空间下 `distance = 1 - 余弦相似度`（0 最近、2 最远） |
| **默认空间是 L2** | 不指定就用欧氏距离，文本检索会怪 | 建表时 `metadata={"hnsw:space": "cosine"}` |
| **embeddings 要 list** | 传 numpy 可能出错 | `vec.tolist()` |

---

## 五、和你 s4_01 手搓版的对照（一眼看清它替你干了啥）

| s4_01（手搓，内存暴力） | Chroma |
|---|---|
| `doc_vecs = list`（进程内，重启就没） | `PersistentClient` 落盘，**持久化** |
| `for` 循环逐条 `cosine_similarity` | `col.query(...)`，内部 **HNSW 近似最近邻索引**（亚线性，扛百万级） |
| 没有过滤能力 | `where={...}` **元数据过滤** |
| `sorted(...)[:k]` 手动取 top-k | `n_results=k` 自动 |
| 相似度越大越好 | **距离越小越近**（cosine: `dist=1-cos`） |

**本质没变**：还是「文本→向量→比相似度→top-K」。Chroma 只是把它做成了**能落盘、能过滤、能快**的产品。所以你手搓那遍不亏——正因为看过内部，才知道它在替你干嘛。

> ⚠️ ANN 是**近似**最近邻：为了快，它**不保证**每次都返回严格的 top-K（可能漏个别真·最近的）。这是"速度换召回"的取舍——上了索引要用 Hit@K/MRR 复核召回没掉太多（接回你的 eval 老本行）。

---

## 六、深入：`hnsw:space` 到底是什么

建表时那句 `metadata={"hnsw:space": "cosine"}`，key 藏了两个概念：`hnsw:`（前缀，指"这是给 HNSW 索引的配置"）+ `space`（用哪种**距离度量**）。

### `space`：用哪种"距离"衡量"近"
决定**"两个向量有多近"怎么算**，也决定 `query` 返回的 `distance` 是什么含义：

| space | 含义 | distance 范围 | 何时用 |
|---|---|---|---|
| **`cosine`** | 1 − 余弦相似度（只看**方向**） | 0~2（0 最近） | **文本 embedding 检索，标准选择** |
| `l2`（默认） | 欧氏距离平方（看**直线距离**，受长度影响） | 0~∞ | 图像/坐标类，或向量已归一化 |
| `ip` | 负内积（点积） | —— | 向量已归一化、想省一步除法 |

**为什么文本要 cosine**：文本语义里**方向代表意思、长度不代表**（见 concepts-basics 余弦那节）。"养老"和"退休储备"方向接近就该算近，不管向量长短。默认 `l2` 会把长度差异也算进去，对没归一化的 embedding 可能排出怪结果——**所以不显式设 cosine，文本检索会翻车**，这就是第四节把它列为"坑"的原因。

### `hnsw`：这是哪种索引
**HNSW = Hierarchical Navigable Small World**，Chroma 内部用的**近似最近邻（ANN）索引算法**。一句话原理：

> 把所有向量组织成一张**多层的"小世界"导航图**——顶层稀疏（少数点、长连接），底层稠密（全部点、短连接）。查询时从顶层入口点出发，**像导航一样"朝更近的邻居跳"、逐层下沉**，几十跳就锁定近邻区，**根本不和每个向量都比**。

对比 s4_01：那是 `for` 循环逐条算 cosine = **O(N) 全表暴力扫**；HNSW 是**图上导航** → **亚线性**，百万级也毫秒返回。这就是向量库"扛量"的底层秘密。代价就是上面说的**近似 / 速度换召回**。

### 合起来
```python
metadata={"hnsw:space": "cosine"}
#          └─HNSW索引─┘ └─用余弦距离建图+搜索─┘
```
即：**"这张表用 HNSW 索引，并用余弦距离衡量远近"**。前缀 `hnsw:` 下还有 `hnsw:M`、`hnsw:construction_ef` 等调"索引精度 vs 速度"的旋钮，入门不用碰。

---

## 七、运行模式、并发与事务（部署必懂）

### 两种运行模式
| | **嵌入式（我们练习用的）** | **服务端** |
|---|---|---|
| 建法 | `chromadb.PersistentClient(path=...)` | `chroma run --path ./data`（默认端口 8000）+ `chromadb.HttpClient(host, port)` |
| 形态 | **就是个库，跑在你 Python 进程里** | **独立后台进程**，监听端口 |
| 启停 | **不用启动/关闭**，进程退出就结束 | 像服务一样起/关/查进程和端口 |
| 数据 | **磁盘上那几个文件**（`chroma.sqlite3` + HNSW 索引目录） | 由服务进程独占管理 |
| 类比 | **SQLite** | **Postgres** |

嵌入式**没有"服务在不在跑"的概念**——它只在你进程活着时"活着"。验证有没有数据：`ls <path>` 看 `chroma.sqlite3` 在不在，或 `client.list_collections()` / `col.count()`。清理：`rm -rf <path>` 或 `client.delete_collection(...)`。

### 并发：嵌入式是"单一属主"，别多进程写
嵌入式除了那个 sqlite 文件，还**在每个进程的内存里各自挂一份 HNSW 索引**。所以：
- **多进程同时写同一 path** → 各持一份内存索引、各自刷盘 → **索引不一致 / 写丢失 / 文件损坏**。不安全。
- **一个写、一个读** → 读进程的内存索引是它**打开那一刻的快照**，看不到新写入（除非重开 client）。

底层 SQLite 的文件锁能挡一部分粗暴冲突，但**跨进程的 HNSW 索引一致性它管不了**——这才是真问题。所以嵌入式的正确用法：**一个进程独占这个 path**（进程内也要把写**串行化**，别开一堆线程乱写）。

### 事务：没有 SQL 意义上的事务
Chroma **没有 `BEGIN/COMMIT/ROLLBACK`、没有隔离级别、没有多操作原子性**。
- 能拿到的最接近的：**一次批量 `upsert`（单调用、一个 batch）** 大致是一个单元，要么整体生效要么报错（但部分失败语义比 ACID 弱）。→ "20 个 chunk 原子入库" 靠**一次 upsert 传 20 条**实现。
- **拿不到的**：把"多次独立调用"包进一个事务保证"要么全成要么全回滚"。

### 按需求选（和"SQLite 何时够 / 何时上 RDBMS"是同一决策）
| 需求 | 用什么 |
|---|---|
| 单进程（一个 API server / worker）读写 | 嵌入式 `PersistentClient` 够用（写串行化） |
| 多进程 / 横向扩展并发 | **服务端** `chroma run` + `HttpClient`：让唯一服务进程仲裁、串行化写 |
| 向量必须和业务数据**强一致（同事务）** | **pgvector**（Postgres 向量扩展）：直接白拿事务/行锁/MVCC |

> 注意：即便 Chroma 服务端也**不是为重事务负载设计**（写串行、无多语句事务）。核心诉求是"向量 + 强事务一致性"时，**pgvector 往往更对**——事务本就是 Postgres 的看家本领，顺带存向量。

**一句话**：嵌入式 = 单属主、无事务，像 SQLite；要并发就升服务端（像 Postgres），要真事务就选 pgvector。
