"""Serve the pinned Kev checkpoint on CPU; reject context overflow instead of truncating."""
import os

RUN = 'jaredpalmer/kev-4b@6cfce5c2fa4b4bd64026336ab649c5ca78857d52'


def strict_encode(self, tok, rec, **kw):
    kw['strict'] = True
    return original_encode(self, tok, rec, **kw)


if __name__ == '__main__':
    import sys
    from kev.model import DecisionModel
    original_encode = DecisionModel.encode
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    os.environ['KEV_DTYPE'] = 'bf16'
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    DecisionModel.encode = strict_encode
    from kev.serve import main
    sys.argv = ['kev.serve', '--run', RUN, '--port', '8008']
    main()
