"""按训练任务汇总：需要几个 worker、几个已运行、几个在等调度、占了几张 GPU，以及"能不能开始训练"。

分布式训练要所有 worker 到齐才能开始（每一步都要一起同步梯度），少一个都只能干等。

    python3 robot-k8s-lab/show_jobs.py
"""
import json
import subprocess
from collections import defaultdict

TOTAL_GPUS = 16


def main() -> None:
    out = subprocess.run(
        ["kubectl", "get", "pods", "-l", "lab=l08", "-o", "json"],
        check=True, capture_output=True, text=True,
    ).stdout
    jobs = defaultdict(lambda: {"need": 0, "running": 0, "pending": 0, "gpus": 0, "nodes": set()})
    for p in json.loads(out)["items"]:
        j = jobs[p["metadata"]["labels"].get("train-job", "?")]
        j["need"] = int(p["metadata"].get("annotations", {}).get("train/workers-needed", 0))
        phase = p["status"].get("phase")
        if phase == "Running":
            j["running"] += 1
            j["nodes"].add(p["spec"].get("nodeName", "?").replace("robot-train-", ""))
            for c in p["spec"]["containers"]:
                j["gpus"] += int(c.get("resources", {}).get("limits", {}).get("nvidia.com/gpu", 0))
        elif phase == "Pending":
            j["pending"] += 1

    print(f"{'任务':<6}{'需要':>4}{'运行':>4}{'等待':>4}{'占用GPU':>8}  状态")
    total = 0
    for name in sorted(jobs):
        j = jobs[name]
        total += j["gpus"]
        if j["need"] and j["running"] == j["need"]:
            state = "✅ 到齐，可以训练"
        elif j["running"]:
            state = "⚠️  没到齐，已启动的 worker 占着卡干等"
        else:
            state = "⏳ 一个都没启动，在排队"
        nodes = ",".join(sorted(j["nodes"]))
        print(f"{name:<6}{j['need']:>4}{j['running']:>4}{j['pending']:>4}{j['gpus']:>8}  {state}  {nodes}")
    print(f"\n集群 GPU 共 {TOTAL_GPUS} 张，已分配 {total} 张")


if __name__ == "__main__":
    main()
