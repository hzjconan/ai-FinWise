"""L05 · 第 6 步动手：并发控制三件套——令牌桶限流、Semaphore 限并发、asyncio.timeout 限时

讲义：docs/ai-agent-learning/lessons/L05-agent-reliability.md（第 6 步）

三个 TODO：
  6a TokenBucket.try_acquire：令牌桶限流（控制每秒请求数 QPS），纯计算、时间由参数传入，方便测试
  6b run_all：用 asyncio.Semaphore 限制同时在跑的请求数（并发数）
  6c call_with_timeout：用 asyncio.timeout 给单次调用设上限，超时返回 "timeout" 而不是一直等

不调用真实 LLM：用 fake_llm_call（asyncio.sleep 模拟耗时）演示。

运行：
    cd backend && .venv/bin/python scratch/s6_03_concurrency_limits.py
测试：
    cd backend && .venv/bin/python -m pytest scratch/test_s6_03_concurrency_limits.py -v
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


# ========================= TODO 6a：令牌桶 =========================

class TokenBucket:
    """令牌桶：桶里最多放 capacity 个令牌，每秒补充 rate 个；每个请求要拿走 1 个令牌才能发出。

    - 平时攒满 capacity 个 → 允许一次突发 capacity 个请求
    - 长期来看每秒最多 rate 个请求（= QPS 上限）
    """

    def __init__(self, rate: float, capacity: int, now: float = 0.0):
        self.rate = rate                  # 每秒补充几个令牌
        self.capacity = capacity          # 桶的容量（最多攒几个）
        self.tokens = float(capacity)     # 一开始是满的
        self.last = now                   # 上次补充令牌的时间点（秒）

    def try_acquire(self, now: float) -> bool:
        """TODO 6a：在时间点 now 尝试拿 1 个令牌。拿到返回 True，没有令牌返回 False。

        两步：
          1. 补充：距上次过去了 (now - self.last) 秒，补充 rate × 经过秒数 个令牌，
             但总数不能超过 capacity（用 min）；然后把 self.last 更新为 now
          2. 拿取：令牌数 ≥ 1 就减 1 并返回 True，否则返回 False（不减）
        """
        # 1. 补充：按经过的时间补令牌，但不超过桶容量
        elapsed = now - self.last
        self.tokens = min(self.capacity, self.tokens + self.rate * elapsed)
        self.last = now
        # 2. 拿取：够 1 个就扣掉，否则拒绝且不扣
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


# ========================= TODO 6b：Semaphore 限并发 =========================

async def run_all(calls: list[Callable[[], Awaitable[str]]], max_concurrency: int) -> list[str]:
    """TODO 6b：并发执行所有 calls，但同一时刻最多 max_concurrency 个在跑；按原顺序返回结果。

    提示：
      sem = asyncio.Semaphore(max_concurrency)
      写一个内部函数 async def guarded(call): async with sem: return await call()
      再用 asyncio.gather(*(guarded(c) for c in calls)) 一起跑（gather 会按传入顺序返回结果）
    """
    sem = asyncio.Semaphore(max_concurrency)

    async def guarded(call: Callable[[], Awaitable[str]]) -> str:
        async with sem:              # 最多 max_concurrency 个同时进入
            return await call()

    # gather 按传入顺序返回结果，与原 calls 顺序一致
    return list(await asyncio.gather(*(guarded(c) for c in calls)))


# ========================= TODO 6c：asyncio.timeout 限时 =========================

async def call_with_timeout(call: Callable[[], Awaitable[str]], seconds: float) -> str:
    """TODO 6c：最多等 seconds 秒；按时完成返回结果，超时返回字符串 "timeout"。

    提示（Python 3.11+）：
      try:
          async with asyncio.timeout(seconds):
              return await call()
      except TimeoutError:
          ...
    """
    try:
        async with asyncio.timeout(seconds):
            return await call()
    except TimeoutError:
        return "timeout"

# =============================================================================


def make_fake_llm_call(name: str, seconds: float, tracker: dict | None = None):
    """返回一个模拟的 LLM 调用：耗时 seconds 秒；tracker 记录"同时在跑的个数"的峰值。"""
    async def call() -> str:
        if tracker is not None:
            tracker["running"] += 1
            tracker["peak"] = max(tracker["peak"], tracker["running"])
        try:
            await asyncio.sleep(seconds)
            return f"{name} 完成"
        finally:
            if tracker is not None:
                tracker["running"] -= 1
    return call


async def main() -> None:
    print("== 6a 令牌桶：rate=2/秒，capacity=3 ==")
    bucket = TokenBucket(rate=2, capacity=3, now=0.0)
    for t in [0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 2.0, 2.0, 2.0, 2.0]:
        print(f"  t={t:.1f}s 请求 → {'放行' if bucket.try_acquire(t) else '拒绝'}（剩余 {bucket.tokens:.1f}）")

    print("\n== 6b Semaphore：10 个请求，每个 0.2 秒 ==")
    for limit in (10, 3):
        tracker = {"running": 0, "peak": 0}
        calls = [make_fake_llm_call(f"请求{i}", 0.2, tracker) for i in range(10)]
        start = time.perf_counter()
        await run_all(calls, max_concurrency=limit)
        print(f"  最多 {limit:>2} 个并发：峰值 {tracker['peak']} 个，总耗时 {time.perf_counter() - start:.2f} 秒")

    print("\n== 6c 超时：上限 0.3 秒 ==")
    for seconds in (0.1, 1.0):
        result = await call_with_timeout(make_fake_llm_call(f"耗时{seconds}秒的请求", seconds), 0.3)
        print(f"  耗时 {seconds} 秒的调用 → {result}")


if __name__ == "__main__":
    asyncio.run(main())
