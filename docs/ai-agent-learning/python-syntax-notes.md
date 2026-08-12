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
