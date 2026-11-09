"""L13：验证融合前向、样本独立性、两种输入的梯度路径和输入契约。"""
import pytest
import torch

from scratch.robot_video_model import VideoStateModel


@pytest.fixture
def model():
    with torch.random.fork_rng():
        torch.manual_seed(42)
        return VideoStateModel()


@pytest.mark.parametrize("batch_size", [1, 8])
def test_prediction_keeps_batch_axis_and_one_action(model, batch_size):
    images = torch.zeros(batch_size, 3, 3, 32, 32)
    state = torch.full((batch_size, 2), 0.5)
    prediction = model(images, state)
    assert prediction.shape == (batch_size, 1)
    assert prediction.dtype == torch.float32
    assert torch.isfinite(prediction).all()


def test_batch_and_individual_predictions_agree(model):
    generator = torch.Generator().manual_seed(9)
    images = torch.rand(4, 3, 3, 32, 32, generator=generator)
    state = torch.rand(4, 2, generator=generator)
    with torch.no_grad():
        batch = model(images, state)
        separate = torch.cat([model(images[i:i + 1], state[i:i + 1])
                              for i in range(4)])
    torch.testing.assert_close(batch, separate)


def test_both_inputs_have_gradient_path_without_updating_parameters(model):
    generator = torch.Generator().manual_seed(12)
    images = torch.rand(2, 3, 3, 32, 32, generator=generator).requires_grad_()
    state = torch.rand(2, 2, generator=generator).requires_grad_()
    before = {name: tensor.detach().clone() for name, tensor in model.named_parameters()}
    model(images, state).sum().backward()
    assert images.grad is not None and torch.count_nonzero(images.grad) > 0
    assert state.grad is not None and torch.count_nonzero(state.grad) > 0
    for name, parameter in model.named_parameters():
        assert torch.equal(parameter.detach(), before[name])


@pytest.mark.parametrize("image_shape,state_shape,match", [
    ((8, 3, 32, 32), (8, 2), "images"),
    ((8, 3, 3, 16, 16), (8, 2), "images"),
    ((8, 3, 3, 32, 32), (7, 2), "state"),
    ((8, 3, 3, 32, 32), (8, 3), "state"),
])
def test_wrong_shapes_are_rejected(model, image_shape, state_shape, match):
    with pytest.raises(ValueError, match=match):
        model(torch.zeros(image_shape), torch.zeros(state_shape))


def test_integer_pixels_require_preprocessing(model):
    with pytest.raises(ValueError, match="float32"):
        model(torch.zeros(2, 3, 3, 32, 32, dtype=torch.uint8), torch.zeros(2, 2))
