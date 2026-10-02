"""Original BF16 weights with per-layer FP32 CPU arithmetic; no quantization."""
import torch
from torch import nn


class FP32ComputeLinear(nn.Linear):
    def forward(self, value):
        # Convert one layer at a time, preserving BF16 storage and output precision.
        # This avoids slow emulated BF16 GEMM on hosted CPUs lacking BF16 instructions.
        result = torch.nn.functional.linear(value.float(), self.weight.float(),
            None if self.bias is None else self.bias.float())
        return result.to(value.dtype)


def use_fp32_linear_compute(model):
    count = 0
    for child in model.lm.modules():
        if isinstance(child, nn.Linear):
            child.__class__ = FP32ComputeLinear
            count += 1
    return count
