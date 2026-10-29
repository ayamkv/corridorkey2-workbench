"""Stands in for sam_worker.py in tests: same JSON-lines protocol, no torch.
The "mask" is a filled disc around every keep-click, minus discs around remove-clicks, or the box."""
import json
import os
import sys

import cv2
import numpy as np

args = sys.argv[1:]
if "--download" in args:
    d = args[args.index("--download") + 1]
    os.makedirs(d, exist_ok=True)
    for name in ("config.json", "preprocessor_config.json", "processor_config.json", "model.safetensors"):
        open(os.path.join(d, name), "w").close()
    sys.exit(0)

device = args[args.index("--device") + 1] if "--device" in args else "cuda"


def say(**kw):
    print(json.dumps(kw), flush=True)


say(ok=True, ready=True, device=device)
size = None
for line in sys.stdin:
    req = json.loads(line)
    if req["cmd"] == "quit":
        say(ok=True)
        break
    if req["cmd"] == "open":
        img = cv2.imdecode(np.fromfile(req["image"], np.uint8), cv2.IMREAD_COLOR)
        size = img.shape[:2]
        say(ok=True, width=size[1], height=size[0], ms=1)
    elif req["cmd"] == "predict":
        m = np.zeros(size, np.uint8)
        if req.get("box"):
            x0, y0, x1, y1 = (int(v) for v in req["box"])
            m[y0:y1, x0:x1] = 255
        for x, y, lab in req.get("points") or []:
            cv2.circle(m, (int(x), int(y)), 20, 255 if lab else 0, -1)
        ok, buf = cv2.imencode(".png", m)
        buf.tofile(req["out"])
        say(ok=True, score=0.9, area=float(m.mean() / 255), ms=1)
