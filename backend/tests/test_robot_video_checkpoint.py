"""L13：checkpoint 内容完整性、不覆盖旧版本及保存失败清理。"""
import hashlib
import random

import numpy as np
import pytest
import torch

from scratch.robot_video_checkpoint import load_checkpoint, save_checkpoint
from scratch.robot_video_model import VideoStateModel
from scratch.robot_video_train import train_step


@pytest.fixture(autouse=True)
def preserve_global_rng():
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    torch_state = torch.get_rng_state().clone()
    yield
    random.setstate(python_state)
    np.random.set_state(numpy_state)
    torch.set_rng_state(torch_state)


@pytest.fixture
def setup(tmp_path):
    with torch.random.fork_rng():
        torch.manual_seed(42)
        model = VideoStateModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    train_step(model, optimizer, {
        "images": torch.zeros(2, 3, 3, 32, 32),
        "state": torch.full((2, 2), 0.5), "action": torch.full((2, 1), -2.0),
    })
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"synthetic": true, "schema_version": 2}\n')
    arguments = {"completed_epoch": 1, "global_step": 1, "manifest_path": manifest,
                 "config": {"model_version": "video-state-mlp-v1", "batch_size": 8},
                 "train_generator": torch.Generator().manual_seed(43),
                 "val_generator": torch.Generator().manual_seed(44)}
    return model, optimizer, arguments


def test_saved_file_contains_weights_adam_progress_and_rng(tmp_path, setup):
    model, optimizer, arguments = setup
    expected_torch_rng = torch.get_rng_state().clone()
    expected_train_rng = arguments["train_generator"].get_state().clone()
    expected_val_rng = arguments["val_generator"].get_state().clone()
    expected_python_rng = random.getstate()
    expected_numpy_rng = np.random.get_state()
    path = tmp_path / "epoch-001.pt"
    assert save_checkpoint(path, model, optimizer, **arguments) == path
    # 只读取本测试刚生成的本地文件；包含 NumPy RNG 状态，显式使用完整加载模式。
    saved = torch.load(path, map_location="cpu", weights_only=False)
    assert saved["format_version"] == 1
    assert saved["completed_epoch"] == saved["global_step"] == 1
    assert saved["config"] == arguments["config"]
    assert saved["manifest_sha256"] == hashlib.sha256(
        arguments["manifest_path"].read_bytes()).hexdigest()
    for name, value in model.state_dict().items():
        assert torch.equal(saved["model"][name], value)
    actual_optimizer = optimizer.state_dict()
    assert saved["optimizer"]["param_groups"] == actual_optimizer["param_groups"]
    for key, state in actual_optimizer["state"].items():
        for field, value in state.items():
            assert torch.equal(saved["optimizer"]["state"][key][field], value)
    assert torch.equal(saved["rng"]["torch"], expected_torch_rng)
    assert torch.equal(saved["rng"]["train_loader"], expected_train_rng)
    assert torch.equal(saved["rng"]["val_loader"], expected_val_rng)
    assert saved["rng"]["python"] == expected_python_rng
    assert np.array_equal(saved["rng"]["numpy"][1], expected_numpy_rng[1])
    assert torch.equal(torch.get_rng_state(), expected_torch_rng)
    assert torch.equal(arguments["train_generator"].get_state(), expected_train_rng)
    assert torch.equal(arguments["val_generator"].get_state(), expected_val_rng)
    assert not list(tmp_path.glob("*.tmp"))


def test_existing_checkpoint_is_not_overwritten(tmp_path, setup):
    model, optimizer, arguments = setup
    path = tmp_path / "epoch-001.pt"
    save_checkpoint(path, model, optimizer, **arguments)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        save_checkpoint(path, model, optimizer, **arguments)
    assert path.read_bytes() == before


def test_save_failure_never_publishes_partial_file(tmp_path, setup, monkeypatch):
    model, optimizer, arguments = setup
    path = tmp_path / "epoch-001.pt"

    def fail(payload, handle):
        handle.write(b"partial checkpoint")
        raise OSError("simulated write failure")

    monkeypatch.setattr("scratch.robot_video_checkpoint.torch.save", fail)
    with pytest.raises(OSError, match="simulated"):
        save_checkpoint(path, model, optimizer, **arguments)
    assert not path.exists()
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("progress", [(-1, 0), (0, -1)])
def test_invalid_progress_is_rejected(tmp_path, setup, progress):
    model, optimizer, arguments = setup
    arguments.update(completed_epoch=progress[0], global_step=progress[1])
    with pytest.raises(ValueError, match="非负整数"):
        save_checkpoint(tmp_path / "invalid.pt", model, optimizer, **arguments)
    assert not (tmp_path / "invalid.pt").exists()


def test_load_restores_parameters_adam_and_all_rng_streams(tmp_path, setup):
    original_model, original_optimizer, arguments = setup
    path = tmp_path / "epoch-001.pt"
    save_checkpoint(path, original_model, original_optimizer, **arguments)
    expected_python = random.random()
    expected_numpy = np.random.random(3)
    expected_torch = torch.rand(3)
    expected_train_order = torch.randperm(20, generator=arguments["train_generator"])
    expected_val_rng = torch.rand(3, generator=arguments["val_generator"])

    random.seed(999)
    np.random.seed(999)
    torch.manual_seed(999)
    model = VideoStateModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.5)
    train_generator = torch.Generator().manual_seed(999)
    val_generator = torch.Generator().manual_seed(1000)
    progress = load_checkpoint(
        path, model, optimizer, manifest_path=arguments["manifest_path"],
        expected_config=arguments["config"], train_generator=train_generator,
        val_generator=val_generator,
    )
    assert progress["completed_epoch"] == progress["global_step"] == 1
    assert progress["optimizer_restored"] is True
    for key, value in original_model.state_dict().items():
        assert torch.equal(model.state_dict()[key], value)
    assert optimizer.param_groups[0]["lr"] == 1e-3
    for key, state in original_optimizer.state_dict()["state"].items():
        for field, value in state.items():
            assert torch.equal(optimizer.state_dict()["state"][key][field], value)
    assert random.random() == expected_python
    np.testing.assert_array_equal(np.random.random(3), expected_numpy)
    assert torch.equal(torch.rand(3), expected_torch)
    assert torch.equal(torch.randperm(20, generator=train_generator), expected_train_order)
    assert torch.equal(torch.rand(3, generator=val_generator), expected_val_rng)


@pytest.mark.parametrize("mismatch", ["data", "config", "format", "progress", "model"])
def test_mismatched_checkpoint_rejected_before_model_mutation(tmp_path, setup, mismatch):
    original_model, original_optimizer, arguments = setup
    path = tmp_path / "epoch-001.pt"
    save_checkpoint(path, original_model, original_optimizer, **arguments)
    expected_config = dict(arguments["config"])
    if mismatch == "data":
        arguments["manifest_path"].write_text('{"different_data": true}')
    elif mismatch == "config":
        expected_config["batch_size"] = 16
    else:
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if mismatch == "model":
            payload["model"][next(iter(payload["model"]))] = torch.zeros(1)
        else:
            payload["format_version" if mismatch == "format" else "global_step"] = (
                999 if mismatch == "format" else -1)
        torch.save(payload, path)
    model = VideoStateModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    before = [parameter.detach().clone() for parameter in model.parameters()]
    rng_before = torch.get_rng_state().clone()
    with pytest.raises(ValueError):
        load_checkpoint(path, model, optimizer, manifest_path=arguments["manifest_path"],
                        expected_config=expected_config,
                        train_generator=arguments["train_generator"],
                        val_generator=arguments["val_generator"])
    assert all(torch.equal(parameter, saved) for parameter, saved in zip(model.parameters(), before))
    assert not optimizer.state
    assert torch.equal(torch.get_rng_state(), rng_before)


def test_optimizer_restore_can_be_disabled_for_controlled_comparison(tmp_path, setup):
    original_model, original_optimizer, arguments = setup
    path = tmp_path / "epoch-001.pt"
    save_checkpoint(path, original_model, original_optimizer, **arguments)
    model = VideoStateModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    result = load_checkpoint(
        path, model, optimizer, manifest_path=arguments["manifest_path"],
        expected_config=arguments["config"], train_generator=arguments["train_generator"],
        val_generator=arguments["val_generator"], restore_optimizer=False,
    )
    assert result["optimizer_restored"] is False
    assert not optimizer.state
    for key, value in original_model.state_dict().items():
        assert torch.equal(model.state_dict()[key], value)
