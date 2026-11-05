"""验证 L08 汇总输出，不连接或修改 Kubernetes 集群。"""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def show_jobs():
    path = Path(__file__).resolve().parents[2] / "robot-k8s-lab" / "show_jobs.py"
    spec = importlib.util.spec_from_file_location("l08_show_jobs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pod(phase, node="robot-train-worker", gpus=4):
    return {
        "metadata": {"labels": {"train-job": "a"},
                     "annotations": {"train/workers-needed": "3"}},
        "status": {"phase": phase},
        "spec": {"nodeName": node, "containers": [
            {"resources": {"limits": {"nvidia.com/gpu": gpus}}},
            {"name": "sidecar"},
        ]},
    }


@pytest.mark.parametrize("phases,allocated,message", [
    (["Running"] * 3, 12, "到齐，可以训练"),
    (["Running", "Pending", "Pending"], 4, "没到齐"),
    (["Pending"] * 3, 0, "一个都没启动"),
])
def test_summary_distinguishes_complete_partial_and_waiting(
    show_jobs, monkeypatch, capsys, phases, allocated, message,
):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        items = [pod(phase, f"robot-train-worker{index}")
                 for index, phase in enumerate(phases)]
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"items": items}))

    monkeypatch.setattr(show_jobs.subprocess, "run", fake_run)
    show_jobs.main()
    output = capsys.readouterr().out
    row = next(line for line in output.splitlines() if line.startswith("a "))
    assert row.split()[:5] == ["a", "3", str(phases.count("Running")),
                              str(phases.count("Pending")), str(allocated)]
    assert message in row
    assert f"已分配 {allocated} 张" in output
    assert calls == [(["kubectl", "get", "pods", "-l", "lab=l08", "-o", "json"],
                      {"check": True, "capture_output": True, "text": True})]


def test_empty_cluster_has_zero_allocated_gpus(show_jobs, monkeypatch, capsys):
    monkeypatch.setattr(show_jobs.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 0, stdout='{"items": []}'))
    show_jobs.main()
    assert "已分配 0 张" in capsys.readouterr().out


def test_kubectl_failure_is_not_reported_as_an_empty_cluster(show_jobs, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="connection refused")

    monkeypatch.setattr(show_jobs.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        show_jobs.main()
    assert capsys.readouterr().out == ""
