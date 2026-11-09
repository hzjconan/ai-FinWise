"""L13：真实视频到参数更新，检查清梯度、Adam 状态和错误标签。"""
import copy

import pytest
import torch
from torch.utils.data import DataLoader

from scratch.robot_video_data import VideoActionDataset, make_fixture
from scratch.robot_video_model import VideoStateModel
from scratch.robot_video_train import evaluate, fit, train_epoch, train_step


@pytest.fixture
def model():
    with torch.random.fork_rng():
        torch.manual_seed(42)
        return VideoStateModel()


def example_batch():
    return {"images": torch.zeros(2, 3, 3, 32, 32),
            "state": torch.tensor([[0.3, 0.5], [0.7, 0.5]]),
            "action": torch.tensor([[-2.0], [2.0]])}


def test_real_video_batch_updates_parameters_and_reduces_same_batch_loss(tmp_path, model):
    manifest = make_fixture(tmp_path, episodes=8)
    dataset = VideoActionDataset(manifest)
    batch = next(iter(DataLoader(dataset, batch_size=8, shuffle=False)))
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    original = [p.detach().clone() for p in model.parameters()]
    with torch.no_grad():
        before = torch.nn.functional.mse_loss(
            model(batch["images"], batch["state"]), batch["action"]).item()
    model.eval()
    reported = train_step(model, optimizer, batch)
    assert model.training is True
    assert reported == pytest.approx(before)
    assert any(not torch.equal(p, old) for p, old in zip(model.parameters(), original))
    assert optimizer.state
    assert {state["step"].item() for state in optimizer.state.values()} == {1.0}
    with torch.no_grad():
        after = torch.nn.functional.mse_loss(
            model(batch["images"], batch["state"]), batch["action"]).item()
    assert after < before


def test_old_gradients_do_not_accumulate_into_next_update(model):
    clean = copy.deepcopy(model)
    for parameter in model.parameters():
        parameter.grad = torch.ones_like(parameter)
    batch = example_batch()
    train_step(model, torch.optim.SGD(model.parameters(), lr=0.01), batch)
    train_step(clean, torch.optim.SGD(clean.parameters(), lr=0.01), batch)
    for actual, expected in zip(model.parameters(), clean.parameters()):
        torch.testing.assert_close(actual, expected)


@pytest.mark.parametrize("invalid_target", [torch.zeros(2), torch.zeros(2, 1, dtype=torch.float64)])
def test_target_shape_or_dtype_error_does_not_update_parameters(model, invalid_target):
    batch = example_batch()
    batch["action"] = invalid_target
    original = [p.detach().clone() for p in model.parameters()]
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    with pytest.raises(ValueError, match="形状与类型"):
        train_step(model, optimizer, batch)
    assert not optimizer.state
    assert all(torch.equal(p, old) for p, old in zip(model.parameters(), original))


def test_nonfinite_loss_does_not_poison_parameters(model):
    batch = example_batch()
    batch["action"][0, 0] = float("nan")
    original = [p.detach().clone() for p in model.parameters()]
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    with pytest.raises(ValueError, match="有限"):
        train_step(model, optimizer, batch)
    assert not optimizer.state
    assert all(torch.equal(p, old) for p, old in zip(model.parameters(), original))


def test_epoch_loss_weights_partial_batch_by_sample_count(monkeypatch):
    batches = [{"action": torch.zeros(8, 1)}, {"action": torch.zeros(4, 1)}]
    losses = iter([1.0, 4.0])
    optimizer = object()
    seen = []

    def fake_step(model, passed_optimizer, batch):
        assert passed_optimizer is optimizer
        seen.append(batch["action"].shape[0])
        return next(losses)

    monkeypatch.setattr("scratch.robot_video_train.train_step", fake_step)
    result = train_epoch(None, optimizer, batches)
    # 8 个误差为 1 的样本、4 个误差为 4 的样本，整体平均为 2，而非 2.5。
    assert result == {"train_mse": 2.0, "samples": 12, "steps": 2}
    assert seen == [8, 4]


def test_epoch_consumes_tail_and_reuses_optimizer_across_rounds(tmp_path, model):
    manifest = make_fixture(tmp_path, episodes=8)
    loader = DataLoader(VideoActionDataset(manifest), batch_size=8, shuffle=False)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    first = train_epoch(model, optimizer, loader)
    assert first["samples"] == 20
    assert first["steps"] == 3
    assert first["train_mse"] >= 0
    assert {state["step"].item() for state in optimizer.state.values()} == {3.0}
    second = train_epoch(model, optimizer, loader)
    assert second["samples"] == 20
    assert second["steps"] == 3
    assert {state["step"].item() for state in optimizer.state.values()} == {6.0}


def test_empty_epoch_is_not_reported_as_zero_error():
    with pytest.raises(ValueError, match="训练数据不能为空"):
        train_epoch(None, None, [])


@pytest.mark.parametrize("training_mode", [True, False])
def test_validation_does_not_change_parameters_gradients_or_mode(tmp_path, model, training_mode):
    manifest = make_fixture(tmp_path, episodes=8)
    val = VideoActionDataset(manifest, split="val")
    loader = DataLoader(val, batch_size=8, shuffle=False)
    model.train(training_mode)
    for parameter in model.parameters():
        parameter.grad = torch.ones_like(parameter)
    before = [(p.detach().clone(), p.grad.clone()) for p in model.parameters()]
    report = evaluate(model, loader)
    assert report["samples"] == 20
    assert report["mse"] >= 0
    assert model.training is training_mode
    for parameter, (value, grad) in zip(model.parameters(), before):
        assert torch.equal(parameter.detach(), value)
        assert torch.equal(parameter.grad, grad)
    whole = next(iter(DataLoader(val, batch_size=20, shuffle=False)))
    with torch.no_grad():
        expected = torch.nn.functional.mse_loss(
            model(whole["images"], whole["state"]), whole["action"]).item()
    assert report["mse"] == pytest.approx(expected, abs=1e-6)


def test_evaluation_weights_tail_and_disables_gradient_recording(model, monkeypatch):
    enabled = []

    def zero_prediction(images, state):
        enabled.append(torch.is_grad_enabled())
        return torch.zeros(images.shape[0], 1)

    monkeypatch.setattr(model, "forward", zero_prediction)
    batches = [
        {"images": torch.zeros(8, 3, 3, 32, 32), "state": torch.zeros(8, 2),
         "action": torch.ones(8, 1)},
        {"images": torch.zeros(4, 3, 3, 32, 32), "state": torch.zeros(4, 2),
         "action": torch.full((4, 1), 2.0)},
    ]
    assert evaluate(model, batches) == {"mse": 2.0, "samples": 12}
    assert enabled == [False, False]


def test_empty_evaluation_fails_and_restores_mode(model):
    model.train()
    with pytest.raises(ValueError, match="评估数据不能为空"):
        evaluate(model, [])
    assert model.training is True


def test_evaluation_shape_error_restores_mode(model):
    batch = example_batch()
    batch["action"] = torch.zeros(2)
    model.train()
    with pytest.raises(ValueError, match="形状与类型"):
        evaluate(model, [batch])
    assert model.training is True


def test_fit_records_baseline_and_keeps_optimizer_progress(tmp_path, model):
    manifest = make_fixture(tmp_path, episodes=8)
    train = DataLoader(VideoActionDataset(manifest), batch_size=8, shuffle=False)
    val = DataLoader(VideoActionDataset(manifest, split="val"), batch_size=8, shuffle=False)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    baseline = evaluate(model, val)
    history = fit(model, optimizer, train, val, epochs=2)
    assert [row["epoch"] for row in history] == [0, 1, 2]
    assert history[0]["train_mse"] is None
    assert history[0]["val_mse"] == pytest.approx(baseline["mse"])
    assert history[0]["steps"] == 0
    assert history[0]["train_samples"] == 0
    for row in history[1:]:
        assert row["train_samples"] == 20
        assert row["val_samples"] == 20
        assert row["steps"] == 3
        assert row["train_mse"] >= 0 and row["val_mse"] >= 0
    assert {state["step"].item() for state in optimizer.state.values()} == {6.0}
    assert history[-1]["val_mse"] == pytest.approx(evaluate(model, val)["mse"])


@pytest.mark.parametrize("epochs", [0, -1])
def test_fit_rejects_invalid_round_count_before_evaluation(epochs):
    with pytest.raises(ValueError, match="epochs"):
        fit(None, None, None, None, epochs=epochs)
