"""Reduce ONNX weight storage while retaining float32 execution."""

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper


def compact_weights(payload):
    model = onnx.load_model_from_string(payload)
    casts = []
    for weight in model.graph.initializer:
        if weight.data_type != TensorProto.FLOAT:
            continue
        name = weight.name
        reduced = numpy_helper.to_array(weight).astype(np.float16)
        weight.CopyFrom(numpy_helper.from_array(reduced, name + ".fp16"))
        casts.append(helper.make_node("Cast", [weight.name], [name], to=TensorProto.FLOAT))
    nodes = list(model.graph.node)
    del model.graph.node[:]
    model.graph.node.extend(casts + nodes)
    return model.SerializeToString()
