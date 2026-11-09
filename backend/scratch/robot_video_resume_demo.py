"""L13：连续训练与跨进程续训对照。依次以 prepare / resume / without-adam 运行。

仓库根目录使用 -m backend.scratch.robot_video_resume_demo。
必填 --manifest、--output-dir 和 --mode；不覆盖已有实验产物。
"""
import argparse
import json
from pathlib import Path
import random

import numpy as np
import torch
from torch.utils.data import DataLoader

from .robot_video_checkpoint import load_checkpoint, save_checkpoint
from .robot_video_data import VideoActionDataset
from .robot_video_model import VideoStateModel
from .robot_video_train import evaluate, fit, train_epoch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["prepare", "resume", "without-adam"], required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    config = {"model_version": "video-state-mlp-v1", "optimizer": "Adam",
              "learning_rate": 0.001, "batch_size": 8, "cpu_threads": 1,
              "data_schema": 2, "train_shuffle": True,
              "torch_version": str(torch.__version__)}
    report_path = args.output_dir / f"{args.mode}.json"
    targets = [report_path]
    if args.mode == "prepare":
        targets += [args.output_dir / "reference-final.pt", args.output_dir / "interrupted-005.pt"]
    elif args.mode == "resume":
        targets += [args.output_dir / "resumed-final.pt"]
    if any(path.exists() for path in targets):
        raise FileExistsError("该阶段输出已存在，请查看原报告或选择新实验目录")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    runs = [("reference", 10), ("interrupted", 5)] if args.mode == "prepare" else [(args.mode, 10)]
    results = {}
    for name, end_epoch in runs:
        seed = 42 if args.mode == "prepare" else 999
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        train = DataLoader(
            VideoActionDataset(args.manifest), batch_size=8, shuffle=True, num_workers=0,
            generator=torch.Generator().manual_seed(seed + 1),
        )
        val = DataLoader(
            VideoActionDataset(args.manifest, split="val"), batch_size=8, shuffle=False,
            num_workers=0, generator=torch.Generator().manual_seed(seed + 2),
        )
        model = VideoStateModel()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
        if args.mode == "prepare":
            history = fit(model, optimizer, train, val, epochs=end_epoch)
            step = sum(row["steps"] for row in history)
            filename = "reference-final.pt" if name == "reference" else "interrupted-005.pt"
            save_checkpoint(
                args.output_dir / filename, model, optimizer, completed_epoch=end_epoch,
                global_step=step, manifest_path=args.manifest, config=config,
                train_generator=train.generator, val_generator=val.generator,
            )
            results[name] = {"checkpoint": filename, "history": history, "global_step": step}
            continue

        # 这是另一条命令启动的新进程；新模型 / Adam / RNG 都先创建，再装回旧状态。
        progress = load_checkpoint(
            args.output_dir / "interrupted-005.pt", model, optimizer,
            manifest_path=args.manifest, expected_config=config,
            train_generator=train.generator, val_generator=val.generator,
            restore_optimizer=args.mode == "resume",
        )
        interrupted = torch.load(args.output_dir / "interrupted-005.pt",
                                 map_location="cpu", weights_only=False)
        initial_weights_equal = all(torch.equal(value, interrupted["model"][key])
                                    for key, value in model.state_dict().items())
        history = []
        step = progress["global_step"]
        for epoch in range(progress["completed_epoch"] + 1, end_epoch + 1):
            training = train_epoch(model, optimizer, train)
            validation = evaluate(model, val)
            step += training["steps"]
            history.append({"epoch": epoch, "train_mse": training["train_mse"],
                            "val_mse": validation["mse"], "train_samples": training["samples"],
                            "val_samples": validation["samples"], "steps": training["steps"]})

        reference = torch.load(args.output_dir / "reference-final.pt",
                               map_location="cpu", weights_only=False)
        preparation = json.loads((args.output_dir / "prepare.json").read_text())
        reference_history = preparation["reference"]["history"]
        weights_equal = all(torch.equal(value, reference["model"][key])
                            for key, value in model.state_dict().items())
        max_difference = max((value - reference["model"][key]).abs().max().item()
                             for key, value in model.state_dict().items())
        current_optimizer = optimizer.state_dict()
        expected_optimizer = reference["optimizer"]
        optimizer_equal = (
            current_optimizer["param_groups"] == expected_optimizer["param_groups"]
            and current_optimizer["state"].keys() == expected_optimizer["state"].keys()
            and all(torch.equal(value, expected_optimizer["state"][key][field])
                    for key, state in current_optimizer["state"].items()
                    for field, value in state.items())
        )
        numpy_rng = np.random.get_state()
        reference_numpy = reference["rng"]["numpy"]
        rng_equal = {
            "python": random.getstate() == reference["rng"]["python"],
            "numpy": (numpy_rng[0] == reference_numpy[0]
                      and np.array_equal(numpy_rng[1], reference_numpy[1])
                      and numpy_rng[2:] == reference_numpy[2:]),
            "torch": torch.equal(torch.get_rng_state(), reference["rng"]["torch"]),
            "train_loader": torch.equal(train.generator.get_state(), reference["rng"]["train_loader"]),
            "val_loader": torch.equal(val.generator.get_state(), reference["rng"]["val_loader"]),
        }
        history_equal = history == reference_history[progress["completed_epoch"] + 1:]
        result = {"mode": args.mode, "initial_weights_equal": initial_weights_equal,
                  "completed_epoch": end_epoch, "global_step": step,
                  "optimizer_restored": progress["optimizer_restored"],
                  "optimizer_steps": sorted({state["step"].item() for state in optimizer.state.values()}),
                  "final_weights_equal_reference": weights_equal,
                  "maximum_parameter_difference": max_difference,
                  "optimizer_equal_reference": optimizer_equal, "rng_equal_reference": rng_equal,
                  "continuation_history_equal_reference": history_equal,
                  "validation_mse": history[-1]["val_mse"],
                  "reference_validation_mse": reference_history[-1]["val_mse"], "history": history}
        if args.mode == "resume":
            assert initial_weights_equal and weights_equal and optimizer_equal
            assert history_equal and all(rng_equal.values())
            save_checkpoint(
                args.output_dir / "resumed-final.pt", model, optimizer,
                completed_epoch=end_epoch, global_step=step, manifest_path=args.manifest,
                config=config, train_generator=train.generator, val_generator=val.generator,
            )
        else:
            assert initial_weights_equal and not weights_equal
        results = result

    if args.mode == "prepare":
        assert results["reference"]["history"][:6] == results["interrupted"]["history"]
    report_path.write_text(json.dumps(results, indent=2) + "\n")
    summary = ({"mode": "prepare", "reference_epochs": 10, "interrupted_epochs": 5,
                "reference_global_step": results["reference"]["global_step"],
                "interrupted_global_step": results["interrupted"]["global_step"]}
               if args.mode == "prepare" else {key: value for key, value in results.items() if key != "history"})
    print(json.dumps({**summary, "report": str(report_path)}, indent=2))


if __name__ == "__main__":
    main()
