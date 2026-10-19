"""Append the SimCC decode to an RTMPose ONNX so DeepStream gets keypoints directly.

RTMPose outputs two score vectors per keypoint (simcc_x: N x 17 x 2W, simcc_y:
N x 17 x 2H). Decoding them in Python would mean copying ~15k floats per person
per frame out of the GPU. This adds ArgMax / ReduceMax to the graph, so the model
outputs one small tensor instead:

    keypoints: N x 17 x 3  =  (x, y, score)

x, y are in network-input pixels (192 x 256 for RTMPose-m); score is the mean of
the two max responses (same as rtmlib / mmpose `get_simcc_maximum`).

    python add_decode.py end2end.onnx rtmpose_kpts.onnx
"""

from __future__ import annotations

import sys

import onnx
from onnx import TensorProto, helper

SPLIT_RATIO = 2.0  # RTMPose simcc_split_ratio


def main(src: str, dst: str) -> None:
    model = onnx.load(src)
    g = model.graph
    if len(g.output) != 2:
        sys.exit(
            f"expected 2 outputs (simcc_x, simcc_y), got {[o.name for o in g.output]}"
        )
    sx, sy = g.output[0].name, g.output[1].name
    opset = max(o.version for o in model.opset_import if o.domain in ("", "ai.onnx"))
    nodes, inits = [], []

    def const(name, value, dtype=TensorProto.FLOAT, dims=()):
        inits.append(
            helper.make_tensor(name, dtype, dims, [value] if not dims else value)
        )
        return name

    half = const("kp_half", 1.0 / SPLIT_RATIO)
    two = const("kp_two", 2.0)
    ax2 = const("kp_axes2", [2], TensorProto.INT64, [1]) if opset >= 18 else None

    def reduce_max(inp, out):
        if opset >= 18:
            nodes.append(helper.make_node("ReduceMax", [inp, ax2], [out], keepdims=1))
        else:
            nodes.append(
                helper.make_node("ReduceMax", [inp], [out], axes=[2], keepdims=1)
            )

    for tag, src_name in (("x", sx), ("y", sy)):
        nodes.append(
            helper.make_node(
                "ArgMax", [src_name], [f"kp_arg_{tag}"], axis=2, keepdims=1
            )
        )
        nodes.append(
            helper.make_node(
                "Cast", [f"kp_arg_{tag}"], [f"kp_argf_{tag}"], to=TensorProto.FLOAT
            )
        )
        nodes.append(helper.make_node("Mul", [f"kp_argf_{tag}", half], [f"kp_{tag}"]))
        reduce_max(src_name, f"kp_max_{tag}")
    nodes.append(helper.make_node("Add", ["kp_max_x", "kp_max_y"], ["kp_sum"]))
    nodes.append(helper.make_node("Div", ["kp_sum", two], ["kp_score"]))
    nodes.append(
        helper.make_node("Concat", ["kp_x", "kp_y", "kp_score"], ["keypoints"], axis=2)
    )

    g.node.extend(nodes)
    g.initializer.extend(inits)
    old = list(g.output)
    batch = old[0].type.tensor_type.shape.dim[0]
    kpts = helper.make_tensor_value_info("keypoints", TensorProto.FLOAT, [None, 17, 3])
    if batch.dim_param:
        kpts.type.tensor_type.shape.dim[0].dim_param = batch.dim_param
    elif batch.dim_value:
        kpts.type.tensor_type.shape.dim[0].dim_value = batch.dim_value
    del g.output[:]
    g.output.append(kpts)
    onnx.checker.check_model(model)
    onnx.save(model, dst)
    print(f"wrote {dst}: output 'keypoints' (N x 17 x 3), opset {opset}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
