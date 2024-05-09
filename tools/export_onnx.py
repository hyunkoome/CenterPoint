import argparse
import torch
import onnx
import onnxsim

from pcdet.config import cfg, cfg_from_yaml_file
from pcdet.models import build_network
from pcdet.utils import common_utils
from pcdet.datasets import DatasetTemplate

class DummyDataset(DatasetTemplate):
    def __init__(self, dataset_cfg, class_names, training=True, root_path=None, logger=None, ext='.bin'):
        super().__init__(
            dataset_cfg=dataset_cfg, class_names=class_names, training=training, root_path=root_path, logger=logger
        )

    def __len__(self):
        return 0

    def __getitem__(self, index):
        return {}

def parse_config():
    parser = argparse.ArgumentParser(description='arg parser')
    parser.add_argument('--cfg_file', type=str, default='cfgs/kitti_models/second.yaml',
                        help='specify the config for demo')
    parser.add_argument('--data_path', type=str, default='demo_data',
                        help='specify the point cloud data file or directory')
    parser.add_argument('--ckpt', type=str, default=None, help='specify the pretrained model')

    args = parser.parse_args()

    cfg_from_yaml_file(args.cfg_file, cfg)

    return args, cfg

def main():
    args, cfg = parse_config()
    logger = common_utils.create_logger()
    logger.info("------ Convert OpenPCDet model to ONNX ------")
    dataset = DummyDataset(
        dataset_cfg=cfg.DATA_CONFIG, class_names=cfg.CLASS_NAMES, training=False,
        root_path=args.data_path, logger=logger
    )

    # Build the model
    cfg.MODEL.DENSE_HEAD.POST_PROCESSING.EXPORT_ONNX = True
    cfg.MODEL.POST_PROCESSING.EXPORT_ONNX = True
    model = build_network(model_cfg=cfg.MODEL, num_class=len(cfg.CLASS_NAMES),
                          dataset=dataset)
    model.load_params_from_file(filename=args.ckpt, logger=logger, to_cpu=True)
    model.cuda()
    model.eval()

    # Prepare the input
    with torch.no_grad():
        for item in cfg.DATA_CONFIG.DATA_PROCESSOR:
            if item.NAME == "transform_points_to_voxels":
                # max_voxels = item.MAX_NUMBER_OF_VOXELS['train']
                max_voxels = 30000
                max_points_per_voxel = item.MAX_POINTS_PER_VOXEL
        num_point_features = 4
        
        dummy_voxels = torch.zeros(
            (max_voxels, max_points_per_voxel, num_point_features),
            dtype=torch.float32, device='cuda'
        )
        dummy_voxel_num = torch.zeros((1,), dtype=torch.int32, device='cuda')
        dummy_voxel_idxs = torch.zeros((max_voxels, 4), dtype=torch.int32, device='cuda')
        
        # Export the model to ONNX
        dummy_input = ((dummy_voxels, dummy_voxel_num, dummy_voxel_idxs),)
        input_names = ['voxels', 'voxel_num', 'voxel_idxs']
        output_names = list(cfg.MODEL.DENSE_HEAD.SEPARATE_HEAD_CFG.HEAD_DICT.keys())+["score", "label"]
        torch.onnx.export(model,
                        dummy_input,
                        "model.onnx",
                        export_params=True,
                        opset_version=14,
                        do_constant_folding=True,
                        keep_initializers_as_inputs=True,
                        input_names=input_names,
                        output_names=output_names)
        onnx_raw = onnx.load("model.onnx")
        onnx_sim, _ = onnxsim.simplify(onnx_raw)
        onnx.save(onnx_sim, "model_sim.onnx")
    
    logger.info("Model exported to model.onnx")
    
if __name__ == '__main__':
    main()