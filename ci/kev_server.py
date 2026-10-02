"""Serve the pinned Kev checkpoint on CPU; reject context overflow instead of truncating."""
import os

RUN = 'jaredpalmer/kev-4b@6cfce5c2fa4b4bd64026336ab649c5ca78857d52'


def strict_encode(self, tok, rec, **kw):
    kw['strict'] = True
    import time
    started = time.monotonic()
    enc = original_encode(self, tok, rec, **kw)
    print('Kev encoded input:', len(enc['ids']), 'tokens;', enc['seg'].count(0), 'state tokens; seconds:', round(time.monotonic() - started, 3), flush=True)
    return enc


if __name__ == '__main__':
    import sys
    from kev.model import DecisionModel
    original_encode = DecisionModel.encode
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    os.environ['KEV_DTYPE'] = 'bf16'
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    DecisionModel.encode = strict_encode
    from kev.checkpoint import Checkpoint
    from kev_cpu import use_fp32_linear_compute
    original_load = Checkpoint.load
    def cpu_load(self, device, opts):
        if str(device) != 'cpu':
            raise ValueError('SOP reviewer must use the configured CPU backend')
        tok, model = original_load(self, device, opts)
        print('FP32 arithmetic layers:', use_fp32_linear_compute(model), flush=True)
        return tok, model
    Checkpoint.load = cpu_load
    from kev.serve import main
    sys.argv = ['kev.serve', '--run', RUN, '--port', '8008']
    main()
