# Python 语法 / 语言特性速查（随学随记）

> 用途：学习过程中遇到的 **Python 语法 / 语言特性 / 标准库用法** 沉淀在这里，
> 和 `concepts-basics.md`（只放 AI/ML 概念）分开，互不混。
> 面向对象：有多年编程经验（JS/TS 背景）、Python 不太熟——尽量用 JS 类比。
> 维护：遇到新的 Python 语法点，讲解后**经用户确认**再追加到本文档。

---

## 目录

- [abc：抽象基类（定义接口/契约）](#abc抽象基类定义接口契约)
- [enumerate：遍历时同时拿下标](#enumerate遍历时同时拿下标)
- [set 去重 + sorted 定序](#set-去重--sorted-定序)
- [可迭代对象 / 迭代器（for 能遍历什么）](#可迭代对象--迭代器for-能遍历什么)
- [可变对象当默认参数（footgun）](#可变对象当默认参数footgun)
- [浮点比较：别用 ==，用 math.isclose](#浮点比较别用--用-mathisclose)
- [推导式 / any / all（对应 JS filter/map/some/every）](#推导式--any--all对应-js-filtermapsomeevery)
- [解包必须数量精确](#解包必须数量精确)
- [Literal 类型标注（vs Enum）](#literal-类型标注vs-enum)
- [解包操作符 * 和 **（展开 list / dict）](#解包操作符--和-展开-list--dict)
- [装饰器 @：把函数"登记"或"包一层"](#装饰器-把函数登记或包一层)
- [包 / 模块路径：from a.b.c import X 对应哪个文件](#包--模块路径from-abc-import-x-对应哪个文件)
- [依赖管理：pyproject.toml vs requirements.txt vs 锁文件](#依赖管理pyprojecttoml-vs-requirementstxt-vs-锁文件)

---

## abc：抽象基类（定义接口/契约）

`from abc import ABC, abstractmethod` —— Python 标准库，用来定义"接口/抽象类"。

- `class Foo(ABC)`：继承 ABC 使 Foo 成为抽象类。
- `@abstractmethod`：标记方法为抽象，**子类必须实现**，否则**实例化时**抛 `TypeError`。

```python
class Encoder(ABC):
    @abstractmethod
    def encode(self, x): ...     # 契约：子类必须实现

class Real(Encoder):
    def encode(self, x): return ...   # 实现了 → 可实例化
```

**JS 类比**：TS 的 `interface` / `abstract class`。区别在**何时检查**：TS 编译时，Python abc 是**运行时（实例化那一刻）**。用途：强制"可插拔"组件都满足同一契约（如 s4_01 的 Encoder，embedding/TF-IDF 都实现它）。

---

## enumerate：遍历时同时拿下标

`enumerate(iterable, start=0)`：一边遍历一边配计数，每步吐 `(序号, 元素)`。

```python
for i, term in enumerate(["a", "b"], 1):   # start=1 → 序号从 1 开始
    print(i, term)     # 1 a / 2 b
```

- 只接受**可迭代对象**（list/生成器/任何实现 `__iter__` 的东西），不挑类型。
- 常见用途：建 `{元素: 下标}` 映射 —— `{t: i for i, t in enumerate(items)}`。

**JS 类比**：`arr.entries()` / `arr.forEach((item, i) => ...)`。

---

## set 去重 + sorted 定序

`{...}`（花括号推导）是 **set 集合**，元素**自动去重**；`sorted(...)` 把它排成**稳定顺序**。

```python
all_terms = sorted({t for toks in docs for t in toks})
#                  └─ set：去重（"养老"出现多次只留一个）─┘
#           └─ sorted：定序（每次跑下标都一样）─┘
```

两个"稳定性"分工：
- **唯一性（不重复）** ← `set`（花括号去重）。
- **确定性（每次跑顺序一样）** ← `sorted`。⚠️ **set 本身无序**，直接 `enumerate(set)` 每次顺序可能不同 → 下标会变；`sorted` 才保证可复现。

---

## 可迭代对象 / 迭代器（for 能遍历什么）

一个对象只要实现 `__iter__`（可迭代协议），就能被 `for` 遍历、被 `enumerate`/`zip` 等包裹——不限于 list。

**惰性迭代器**：不是"装好所有元素的列表"，而是**每次 `next()` 才算出下一个**，且可带副作用。例：SDK 的 `tool_runner` 返回的 runner 可迭代，**遍历它的每一步都在幕后跑完一轮 agent**（执行工具→回喂→再调 API 备下一轮）。所以：

```python
for message in runner:   # 每摇一下 = agent 走一步；模型不再调工具 → 迭代结束 → 循环停
    ...
```

即"遍历 runner"这个动作本身在**驱动 agent loop**——手写 loop 的 `break` 变成了"迭代器耗尽"。**JS 类比**：generator / `Symbol.iterator` / `for...of`。

---

## 可变对象当默认参数（footgun）

```python
def f(d={}):     # ⚠️ 默认值在 def 时求值【一次】，所有调用共享同一个 dict
    ...
```

- 陷阱：某次调用 mutate 了它，会泄漏到后续所有调用。ruff `B006` 会警告**字面量**默认值。
- **注意**：把它抽成常量 `_D={}; def f(d=_D)` **不修**陷阱（还是同一个对象共享），只改善命名 —— ruff 可能因此不报（但风险还在）。
- **真修**：用 None 哨兵 + 函数体内新建：
  ```python
  def f(d=None):
      if d is None: d = {}   # 每次调用新建，不共享
  ```
- 例外：若函数从不 mutate 该参数、或需要 None 透传（如把 None 当"未提供"信号传给下游校验），用可变默认是可接受的。

---

## 浮点比较：别用 ==，用 math.isclose

`0.1 + 0.2 == 0.3` → **False**（浮点精度）。正确做法：

```python
import math
math.isclose(0.1 + 0.2, 0.3)          # True（标准库）
np.isclose(a, b) / np.allclose(arr)   # numpy 版
abs(a - b) < 1e-9                      # 手写容差
```

⚠️ `math.isclose` 默认用**相对**容差，**和 0 比会失效** → 跟 0 比要给绝对容差：`math.isclose(x, 0, abs_tol=1e-12)`。
（例外：判"精确零"可用 `== 0`，如 `sqrt(0)==0` 是精确的；只有判"近似零"才需阈值。）

---

## 推导式 / any / all（对应 JS filter/map/some/every）

Python 的 list **没有** `.filter/.map/.some/.every`——用推导式和内置函数：

| JS | Python |
|---|---|
| `arr.map(fn)` | `[fn(x) for x in arr]` |
| `arr.filter(fn)` | `[x for x in arr if fn(x)]` |
| `arr.some(fn)` | `any(fn(x) for x in arr)` |
| `arr.every(fn)` | `all(fn(x) for x in arr)` |

`any`/`all` 配**生成器表达式**（圆括号或直接作参数）会**短路**。嵌套 = 嵌套的 some/every：
```python
any(any(cond for b in m["content"]) for m in msgs)   # msgs.some(m => m.content.some(b => cond))
```
⚠️ 漏 `assert` 的裸表达式（如单独一行 `x == y`）**静默通过、什么都不测**；ruff `B015` 能抓。

---

## 解包必须数量精确

```python
a, b = func()          # func 必须正好返回 2 个，否则 ValueError（too many/not enough）
a, b, *rest = func()   # * 吞掉剩余（rest 是 list）
a, b, *_ = func()      # 只取前 2 个、丢弃其余（四元组只要前两个常用这个）
```

不像 JS 解构可以只取前几个、多的自动忽略——**Python 数量必须对上**（用 `*_` 吞尾部）。

---

## Literal 类型标注（vs Enum）

`from typing import Literal`（标准库，PEP 586，Python 3.8+）。把值**限定为"这几个字面量之一"**：
```python
def f(x) -> Literal["a", "b"]:    # 返回值只可能是 "a" 或 "b"
    ...
mode: Literal["r", "w", "a"]      # 只能取这三个字符串之一
status: Literal[200, 404]         # 数字/布尔字面量也行
```
**只是类型标注、运行时不强制**（`return "xyz"` 照跑不报错）——给类型检查器（mypy/pyright/IDE）看，价值是开发期抓错 + 自文档。

**框架常"消费"它**：LangGraph 读路由函数的 `Literal` 返回标注来画条件边、pydantic/FastAPI 读类型注解做校验/解析——注解是 Python 的，框架只是利用。所以学会它到处能用。

### vs Enum
| | `Literal["r","w"]` | `Enum` |
|---|---|---|
| 本质 | 类型注解（别名） | 一个**类**，成员是对象 |
| 运行时实体 | 无（纯静态提示） | **有**，`Mode.R` 是真实对象 |
| 值 | 就是字面量本身 `"r"` | 成员对象，`.value` 才是 `"r"` |
| 运行时强制 | 不检查 | 真实（得用 `Mode.R`） |
| 带行为 | 不能 | 能：方法、`list(Mode)` 迭代、`.name/.value`、防重复 |
| 重量 | 极轻（一行） | 重（定义类） |

```python
def set_mode(m: Literal["r", "w"]): ...；  set_mode("r")          # 直接传字符串
class Mode(Enum): R="r"; W="w"
def set_mode(m: Mode): ...；               set_mode(Mode.R)       # 传枚举成员对象
```

**怎么选**：值本来就是简单字符串/数字、只想约束取值、不想多定义类 → **Literal**（轻）。需要运行时具名常量、迭代、带方法/行为、强类型对象 → **Enum**（重但强）。
（lg_02 路由函数返回节点名字符串，LangGraph 期望字符串 → 用 Literal 最自然；用 Enum 还得 `.value` 转回字符串反而绕。）

---

## 解包操作符 `*` 和 `**`（展开 list / dict）

`*` 展开**可迭代对象**（list/tuple），`**` 展开**字典**。常见于两处：**构造新容器**、**函数调用传参**。

**① 字典字面量里 `**`：把一个 dict 的键值对"摊进"新 dict**（s4_05 chunk 的 metadata 就这么拼）：
```python
doc_meta = {"product_code": "P-TECH", "risk_level": "C5"}
row = {**doc_meta, "chunk_index": 0, "page": 3}
# 等价于：
#   row = dict(doc_meta)     # 复制 doc_meta 所有字段（浅拷贝，生成新 dict）
#   row["chunk_index"] = 0
#   row["page"] = 3
# → {"product_code":"P-TECH", "risk_level":"C5", "chunk_index":0, "page":3}
```
两个要点：
- **生成一个新 dict**（浅拷贝顶层）——循环里每次 `{**doc_meta, ...}` 都是**独立对象**，20 个 chunk 不会共享同一个 metadata（否则改一个全变，是经典 footgun，呼应 [[可变对象当默认参数footgun]]）。
- **后写的键覆盖先写的**——`{**doc_meta, "risk_level": "C3"}` 会把继承来的 `risk_level` 改成 C3。

**② list 字面量里 `*`：把一个 list 展开进新 list**：
```python
a = [1, 2]
b = [0, *a, 3]        # [0, 1, 2, 3]
merged = [*list1, *list2]   # 拼接两个 list
```

**③ 函数调用时 `*args` / `**kwargs`：把序列/字典拆成实参**：
```python
def f(x, y, z): ...
args = [1, 2, 3];      f(*args)              # 等价 f(1, 2, 3)
kw = {"x":1,"y":2,"z":3}; f(**kw)            # 等价 f(x=1, y=2, z=3)
```

**一句话记**：`*` 拆**位置**（list/tuple），`**` 拆**键值**（dict）；在字面量里是"摊开合并"，在调用里是"拆成实参"。（这和函数定义里的 `def f(*args, **kwargs)` 是同一符号的"反向"——定义时是"收集"，调用/字面量时是"展开"。）

---

## 装饰器 @：把函数"登记"或"包一层"

（L03 第 5 步：`@server.tool(...)`）

**语法本质**：`@xxx` 写在函数定义上方，等价于"定义完函数后，立刻把它交给 `xxx` 处理，并用返回值替换原函数名"：
```python
@server.tool(description="查产品")
def search_products(risk_level: str) -> dict: ...

# 等价于：
def search_products(risk_level: str) -> dict: ...
search_products = server.tool(description="查产品")(search_products)
#                 └─ 先调用 tool(...) 得到一个"装饰器函数"，再把 search_products 传进去
```
- 带括号的 `@server.tool(...)` 是**两步**：`tool(...)` 先返回一个装饰器，装饰器再接收函数。不带括号的 `@decorator` 是一步。
- `server` 是**本文件创建的对象**（`server = MCPServer(...)`），不是 import 进来的；`.tool` 是它的方法。

**两种常见用途**：

| 用途 | 做什么 | 例子 |
|---|---|---|
| **登记** | 把函数记到某个表里，原函数基本不变 | FastAPI `@router.get("/products")`（登记到路由表）；MCP `@server.tool()`（登记到工具表） |
| **包一层** | 返回一个新函数，在原函数前后加逻辑 | 计时、重试、缓存（`@functools.lru_cache`）、权限检查 |

**MCP 里装饰器还做了什么**：SDK 读函数的**名字、参数类型注解、`Field(description=...)`、`description`**，自动生成 `tools/list` 里的工具 schema——相当于自动生成了 FinWise 手写的 `TOOLS_SCHEMA`。

**JS 对照**：TS 也有 `@Decorator` 语法（Angular / NestJS 常见，如 NestJS 的 `@Get('/products')`），作用相同；没有装饰器语法时就是高阶函数：`const f2 = withRetry(f)`。

---

## 包 / 模块路径：from a.b.c import X 对应哪个文件

（L03 第 5 步：`from mcp.server.mcpserver import MCPServer`）

**点号路径 = 磁盘目录层级**：
```
from mcp.server.mcpserver import MCPServer
     └─ site-packages/mcp/server/mcpserver/__init__.py 里导出的 MCPServer

from app.services.chat_service import _execute_tool
     └─ backend/app/services/chat_service.py 里的 _execute_tool
```
- **包（package）**= 一个目录（通常带 `__init__.py`）；**模块（module）**= 一个 `.py` 文件。
- 第三方包装在当前 venv 的 `site-packages/` 下（如 `mcp-lab/.venv/lib/python3.12/site-packages/mcp/`）；自己项目的代码要在 `sys.path` 里能找到（`finwise_mcp_server.py` 开头就是把 `backend/` 加进 `sys.path`，才能 `import app`）。
- **`from 包 import 名字` 只把"名字"带进当前文件，不会绑定包名**：写了 `from mcp.server.mcpserver import MCPServer` 之后，当前文件里并没有一个叫 `mcp` 的东西——所以若再写 `mcp = MCPServer(...)`，这个 `mcp` 只是普通变量（容易和包名看混，故改名 `server`）。
- 查一个模块在哪：`python -c "import mcp.server.mcpserver as m; print(m.__file__)"`；查包信息：`pip show mcp`。

**`sys.path` 的顺序：第一个找到的就用**（L03 追问：`insert(0, ...)` 换成 `append(...)` 会怎样）
```
默认：0 ''（脚本目录） → 1~3 标准库 → 4 venv 的 site-packages
sys.path.insert(0, X)：X 最先被查找        sys.path.append(X)：X 最后被查找
```
| 情况（临时目录实测） | `insert(0)` | `append` |
|---|---|---|
| 脚本目录有个同名 `app.py` | ✅ 拿到 X 里的 app | ❌ 被同名 app.py 抢走 |
| X 里有个 `logging.py` | ❌ 标准库 logging 被顶替（整个程序受影响） | ✅ 用标准库 |
- `insert(0)`：保证拿到你要的包，但可能**顶替**同名标准库 / 第三方包；`append`：不顶替别人，但可能被前面的**同名模块抢走**。
- 隐蔽细节：**没有 `__init__.py` 的目录是"命名空间包"**，查找时遇到会记下来继续往后找；后面若有真正的普通包（有 `__init__.py`），用真正的。所以 `backend/alembic/`（迁移脚本目录）不会顶替 pip 装的 alembic。
- 根本解法：把项目**作为包安装**（`pip install -e ../backend`），不手动改 `sys.path`。

**JS 对照**：`from a.b import X` ≈ `import { X } from 'a/b'`；`site-packages/` ≈ `node_modules/`。

---

## 依赖管理：pyproject.toml vs requirements.txt vs 锁文件

（L03 第 5 步：给 `mcp-lab`、`langgraph-lab` 补 `requirements.txt`，给 backend 的 `pyproject.toml` 补 `scratch` 组）

| | `pyproject.toml` | `requirements.txt` |
|---|---|---|
| 是什么 | 官方标准（PEP 621）的**项目描述文件** | 纯文本**包清单**，每行一个包 |
| 写什么 | 项目名、版本、依赖、可选依赖组、**打包配置**、工具配置（pytest 等） | 只有包名和版本 |
| `pip install -e .` 装项目本身 | ✅ 项目成为可安装、可 import 的包 | ❌ 只装依赖 |
| 适合 | 正式应用 / 库（backend 有 `app/` 包） | 零散脚本（`mcp-lab`、`langgraph-lab`） |

**JS 对照**：`pyproject.toml` ≈ `package.json`；`requirements.txt` ≈ 把 `npm install a@1.0 b@2.0` 写进文件；**锁文件** ≈ `package-lock.json`。

**锁文件**：`requirements.txt` / `pyproject.toml` 通常只写**直接依赖**；间接依赖（如 mcp 依赖的 anyio、starlette）没钉，升级也可能出问题。要完全可复现 → 锁文件钉死全部版本：`pip freeze > requirements.lock`，或用 **uv**（`uv.lock`）、**Poetry**（`poetry.lock`）、pip-tools。新项目趋势：**全用 `pyproject.toml` + 锁文件**。

**范围 vs 精确版本**：
- `fastapi>=0.115.0`（范围）：**库**的惯例，方便被别人的项目兼容。
- `torch==2.2.2`（精确）：**应用 / 环境**的惯例（或交给锁文件）。backend 的 `scratch` 组钉死，是因为 torch 2.2.2 要求 numpy<2，实测过的组合。

**可选依赖组**（`[project.optional-dependencies]`）：`pip install -e ".[dev,scratch]"` 才装；生产 `pip install .` 不装 → 大包（torch）不进生产。

**打包配置的坑**：项目根下有多个顶层目录（`app/`、`scratch/`、`alembic/`…）时，setuptools 自动发现会拒绝打包、`pip install -e .` 失败 → 写 `[tool.setuptools.packages.find] include = ["app*"]` 明确只打包 `app`。

**为什么要钉版本**（这次的真实例子）：`mcp` 1.x → 2.x 把 `FastMCP` 改名为 `MCPServer`，不钉版本的话别人装到新版，代码直接 import 报错。

