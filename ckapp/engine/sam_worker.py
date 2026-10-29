"""Click-to-mask worker: SAM 2.1 tiny, run with CorridorKey's python (torch + transformers live there).

    python sam_worker.py --model DIR [--device cuda|cpu]     JSON lines on stdin/stdout
    python sam_worker.py --download DIR                      fetch the pinned weights (safetensors only)

Requests, one JSON object per line:
    {"cmd": "open", "image": "frame.png"}        embed an image once (RGB, display-referred)
    {"cmd": "predict", "points": [[x, y, 1|0], ...], "box": [x0, y0, x1, y1] | null, "out": "mask.png"}
                                                 writes an 8-bit single-channel mask (255 = keep)
    {"cmd": "quit"}
Every reply is one JSON line with "ok". Only stdlib, numpy, cv2, torch and transformers are used.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

REPO = "facebook/sam2.1-hiera-tiny"
REVISION = "de431c4043854a71d8101e17995dfe596bf101a5"       # pinned (2025-08-15)
FILES = ("config.json", "preprocessor_config.json", "processor_config.json", "model.safetensors")


def reply(**kw) -> None:
    sys.stdout.write(json.dumps(kw) + "\n")
    sys.stdout.flush()


def download(model_dir: str) -> int:
    from huggingface_hub import hf_hub_download
    os.makedirs(model_dir, exist_ok=True)
    for name in FILES:                       # the .pt checkpoint (a pickle) is never fetched
        hf_hub_download(REPO, name, revision=REVISION, local_dir=model_dir)
        reply(ok=True, downloaded=name)
    return 0


def _imread(path: str):
    import cv2
    import numpy as np
    img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot read {path}")
    return np.ascontiguousarray(img[..., ::-1])            # BGR -> RGB


def _imwrite(path: str, img) -> None:
    import cv2
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError(f"cannot encode {path}")
    tmp = path + ".tmp"
    buf.tofile(tmp)
    os.replace(tmp, path)


def serve(model_dir: str, device: str) -> int:
    import numpy as np
    import torch
    from transformers import Sam2Model, Sam2Processor
    from transformers.utils import logging as hf_logging
    hf_logging.set_verbosity_error()

    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
    proc = Sam2Processor.from_pretrained(model_dir, local_files_only=True)
    model = Sam2Model.from_pretrained(model_dir, local_files_only=True).to(device).eval()
    reply(ok=True, ready=True, device=device)

    emb, sizes, key = None, None, None
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        t0 = time.time()
        try:
            req = json.loads(line)
            cmd = req.get("cmd")
            if cmd == "quit":
                reply(ok=True)
                return 0
            if cmd == "open":
                path = req["image"]
                k = (path, os.path.getmtime(path))
                if k != key:
                    img = _imread(path)
                    inputs = proc(images=img, return_tensors="pt").to(device)
                    with torch.inference_mode():
                        emb = model.get_image_embeddings(inputs["pixel_values"])
                    sizes, key = inputs["original_sizes"], k
                h, w = (int(v) for v in sizes[0])
                reply(ok=True, width=w, height=h, ms=round((time.time() - t0) * 1000))
            elif cmd == "predict":
                if emb is None:
                    raise ValueError("no image open")
                pts = req.get("points") or []
                box = req.get("box")
                if not pts and not box:
                    raise ValueError("add a point or a box")
                kw = {}
                if pts:
                    kw["input_points"] = [[[[float(x), float(y)] for x, y, _ in pts]]]
                    kw["input_labels"] = [[[int(lab) for _, _, lab in pts]]]
                if box:
                    kw["input_boxes"] = [[[float(v) for v in box]]]
                p = proc(images=None, original_sizes=sizes, return_tensors="pt", **kw).to(device)
                args = {k: p[k] for k in ("input_points", "input_labels", "input_boxes") if k in p}
                with torch.inference_mode():
                    out = model(image_embeddings=emb, multimask_output=False, **args)
                mask = proc.post_process_masks(out.pred_masks.cpu(), sizes)[0][0, 0].numpy()
                _imwrite(req["out"], mask.astype(np.uint8) * 255)
                reply(ok=True, score=round(float(out.iou_scores.flatten()[0]), 4),
                      area=round(float(mask.mean()), 5), ms=round((time.time() - t0) * 1000))
            else:
                raise ValueError(f"unknown command {cmd!r}")
        except Exception as e:  # report and keep serving
            reply(ok=False, error=f"{type(e).__name__}: {e}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--download")
    a = ap.parse_args()
    if a.download:
        return download(a.download)
    try:
        return serve(a.model, a.device)
    except Exception as e:  # e.g. missing weights: tell the engine instead of dying silently
        reply(ok=False, error=f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
