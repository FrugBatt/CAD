from models.diffusion import DiffusionModule
import hydra
import os
from metrics.sample_and_eval import SampleAndEval
from lightning_fabric.utilities.rank_zero import _get_rank

from pathlib import Path

from omegaconf import OmegaConf
import torch
import wandb

torch.set_float32_matmul_precision("high")


@hydra.main(config_path="configs", config_name="config", version_base=None)
def validate(cfg):
    # print(OmegaConf.to_yaml(cfg, resolve=True))

    dict_config = OmegaConf.to_container(cfg, resolve=True)
    log_dict = {}

    log_dict["model"] = dict_config["model"]

    log_dict["data"] = dict_config["data"]

    datamodule = hydra.utils.instantiate(cfg.data.datamodule)

    rank = _get_rank()

    if os.path.isfile(Path(cfg.checkpoints.dirpath) / Path("wandb_id.txt")):
        with open(
            Path(cfg.checkpoints.dirpath) / Path("wandb_id.txt"), "r"
        ) as wandb_id_file:
            wandb_id = wandb_id_file.readline()
    else:
        wandb_id = wandb.util.generate_id()
        print(f"generated id{wandb_id}")
        if rank == 0 or rank is None:
            with open(
                Path(cfg.checkpoints.dirpath) / Path("wandb_id.txt"), "w"
            ) as wandb_id_file:
                wandb_id_file.write(str(wandb_id))

    if hasattr(cfg, "checkpoint_name"):
        print("Loading checkpoints")
        checkpoint_path = Path(cfg.checkpoints.dirpath) / Path(cfg.checkpoint_name)

    elif (Path(cfg.checkpoints.dirpath) / Path("last.ckpt")).exists():
        print("Loading checkpoints")
        checkpoint_path = Path(cfg.checkpoints.dirpath) / Path("last.ckpt")
    else:
        raise ValueError("No checkpoint found")

    logger = hydra.utils.instantiate(cfg.logger, id=wandb_id, resume=wandb_id)
    logger._wandb_init.update({"config": log_dict})
    model = DiffusionModule.load_from_checkpoint(
        checkpoint_path, cfg=cfg.model, strict=False
    )

    ckpt = torch.load(checkpoint_path)

    global_step = ckpt["global_step"]
    epoch = ckpt["epoch"]

    metric_logger = SampleAndEval(
        logger,
        compute_conditional=cfg.checkpoints.validate_conditional,
        compute_unconditional=cfg.checkpoints.validate_unconditional,
        compute_per_class_metrics=cfg.checkpoints.validate_per_class_metrics,
        log_prefix="val",
        eval_set=cfg.checkpoints.eval_set,
        dataset_name=cfg.data.name,
        num_classes=cfg.data.label_dim,
        dataset_type=cfg.data.type,
        shape=(
            cfg.model.network.num_input_channels,
            cfg.data.data_resolution,
            cfg.data.data_resolution,
        ),
        cfg_rate=cfg.model.cfg_rate if hasattr(cfg.model, "cfg_rate") else 0,
        negative_prompts=(
            cfg.model.negative_prompts
            if hasattr(cfg.model, "negative_prompts")
            else None
        ),
        confidence_value=(
            cfg.model.confidence_value
            if hasattr(cfg.model, "confidence_value")
            else 1.0
        ),
        use_clip_for_fid=True,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    datamodule.setup()
    metric_logger.compute_and_log_metrics(
        device, model, datamodule, step=global_step, epoch=epoch
    )


if __name__ == "__main__":
    validate()
