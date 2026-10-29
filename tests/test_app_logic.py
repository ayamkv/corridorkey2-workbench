"""App logic that needs no GPU or window: clip -> job spec, ranges, sessions, media, timeline maths."""
from __future__ import annotations

import os
import subprocess
import sys

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ckapp.app.media import (ExrOutputSource, frame_paths, open_source, probe, to_display_u8,  # noqa: E402
                             to_frame)
from ckapp.app.model import Clip, ClipSettings, Render, Session  # noqa: E402
from ckapp.app.timeline import tick_steps  # noqa: E402

UPSTREAM = os.environ.get("CK_ROOT", r"D:\CODE\CorridorKey2.0")


def make_clip(frames=100, **settings) -> Clip:
    c = Clip("D:/clips/shot.mp4", "video", frames, 24.0, 1920, 1080)
    for k, v in settings.items():
        setattr(c.settings, k, v)
    return c


# ------------------------------------------------------------------------- ranges / specs
def test_entire_clip_sends_no_range():
    spec = make_clip().to_spec("out")
    assert spec.frame_in is None and spec.frame_out is None


def test_custom_range_maps_to_spec():
    spec = make_clip(range_mode="custom", frame_in=10, frame_out=42).to_spec("out")
    assert (spec.frame_in, spec.frame_out) == (10, 42)


def test_custom_range_covering_everything_sends_no_range():
    spec = make_clip(range_mode="custom", frame_in=0, frame_out=99).to_spec("out")
    assert spec.frame_in is None and spec.frame_out is None


@pytest.mark.parametrize("fin,fout,expect", [(-5, 10, (0, 10)), (50, 20, (50, 50)), (90, 500, (90, 99)),
                                             (200, -1, (99, 99)), (5, -1, (5, 99))])
def test_range_is_clamped(fin, fout, expect):
    assert make_clip(range_mode="custom", frame_in=fin, frame_out=fout).frame_range() == expect


def test_memory_modes():
    assert make_clip(memory="auto").to_spec("o").auto_vram is True
    low = make_clip(memory="low").to_spec("o")
    assert low.low_vram and not low.auto_vram
    man = make_clip(memory="manual", manual_low_vram=False, hann_chunk=8, hann_stride=4).to_spec("o")
    assert (man.auto_vram, man.low_vram, man.hann_chunk, man.hann_stride) == (False, False, 8, 4)


def test_hint_without_file_is_not_sent():
    assert make_clip(hint_mode="first", hint_path="").to_spec("o").hint_mode == "none"


def test_render_dirs_increment(tmp_path):
    c = Clip(str(tmp_path / "a.mov"), "video", 10, 24, 64, 64)
    d1, l1 = c.next_render_dir()
    assert d1.endswith(os.path.join("a_ck2", "render_001")) and l1 == "Render 1"
    c.renders.append(Render("j1", d1, 0, 9, "video"))
    d2, l2 = c.next_render_dir()
    assert d2.endswith("render_002") and l2 == "Render 2"
    os.makedirs(os.path.join(c.render_root(), "render_003"))
    c.renders.append(Render("j2", d2, 0, 9, "video"))
    assert c.next_render_dir()[0].endswith("render_004")


def test_session_round_trip(tmp_path):
    clip_file = tmp_path / "x.mp4"
    clip_file.write_bytes(b"")
    s = Session(tmp_path / "session.json")
    c = Clip(str(clip_file), "video", 50, 25.0, 1280, 720)
    c.settings.range_mode, c.settings.frame_in, c.settings.frame_out, c.settings.despill = "custom", 3, 30, 0.36
    c.renders.append(Render("job1", str(tmp_path / "r1"), 3, 30, "exr", status="done",
                            outputs={"alpha": "a"}, label="Render 1"))
    s.clips.append(c)
    s.save()
    s2 = Session(tmp_path / "session.json")
    s2.load()
    c2 = s2.clips[0]
    assert c2.id == c.id and c2.settings == c.settings and c2.frame_range() == (3, 30)
    assert c2.latest_render().outputs == {"alpha": "a"} and not c2.error
    clip_file.unlink()
    s3 = Session(tmp_path / "session.json")
    s3.load()
    assert s3.clips[0].error == "missing"


def test_settings_ignore_unknown_keys():
    assert ClipSettings.from_dict({"despill": 0.2, "from_the_future": 1}).despill == 0.2


# ------------------------------------------------------------------------- media
@pytest.mark.skipif(not os.path.isdir(os.path.join(UPSTREAM, "corridorkey")), reason="upstream repo not found")
def test_frame_paths_match_upstream(tmp_path):
    names = ["b_0002.png", "a_0010.jpg", "A_0001.EXR", "c.jpeg", "z.txt", "m_0003.exr"]
    for n in names:
        (tmp_path / n).write_bytes(b"")
    ours = frame_paths(str(tmp_path))
    py = os.path.join(UPSTREAM, ".venv", "Scripts", "python.exe")
    if not os.path.isfile(py):
        pytest.skip("upstream venv not found")
    code = ("import sys,json; sys.path.insert(0, sys.argv[1]); from corridorkey.video_io import frame_paths;"
            "print(json.dumps(frame_paths(sys.argv[2])))")
    out = subprocess.run([py, "-c", code, UPSTREAM, str(tmp_path)], capture_output=True, text=True, check=True)
    import json
    assert ours == json.loads(out.stdout)


def test_to_frame_conversions():
    bgr = np.zeros((4, 6, 3), np.uint8)
    bgr[..., 0] = 255                          # blue in BGR
    fr = to_frame(bgr)
    assert fr.data.shape == (4, 6, 3) and fr.data[0, 0, 0] == 255 and fr.data[0, 0, 2] == 0   # BGR kept
    assert fr.data.base is None or fr.data.flags["C_CONTIGUOUS"]
    thumb = to_display_u8(fr, 3)
    assert thumb[0, 0, 2] == 255 and thumb[0, 0, 0] == 0                                     # RGB for Qt
    f16 = to_frame(np.full((2, 2), 70000.0, np.float32), linear=True)
    assert f16.data.dtype == np.float16 and f16.data.shape == (2, 2, 1) and np.isfinite(f16.data).all()
    assert to_frame(np.full((2, 2, 3), 65535, np.uint16)).data.max() == 255


def test_exr_output_source_maps_source_frames(tmp_path):
    import cv2
    d = tmp_path / "shot_alpha_exr"
    d.mkdir()
    for f in (5, 6, 7):
        cv2.imwrite(str(d / f"alpha_{f:06d}.exr"), np.full((8, 8), f / 10, np.float32))
    src = open_source(str(d), gray=True)
    assert isinstance(src, ExrOutputSource)
    assert src.read(4) is None and src.read(8) is None
    fr = src.read(6)
    assert fr.linear and abs(float(fr.data[0, 0, 0]) - 0.6) < 1e-3


def test_probe_video_and_sequence(tmp_path):
    import cv2
    vid = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=25:d=1",
                    "-pix_fmt", "yuv420p", str(vid)], check=True)
    info = probe(str(vid))
    assert (info.kind, info.frames, info.width, info.height, info.fps) == ("video", 25, 160, 90, 25.0)
    seq = tmp_path / "seq"
    seq.mkdir()
    for i in range(3):
        cv2.imwrite(str(seq / f"f_{i:04d}.png"), np.zeros((20, 30, 3), np.uint8))
    info = probe(str(seq), seq_fps=30)
    assert (info.kind, info.frames, info.width, info.height, info.fps) == ("sequence", 3, 30, 20, 30)
    src = open_source(str(vid))
    a, b = src.read(10), src.read(3)          # backwards seek
    again = src.read(10)
    assert a is not None and b is not None and np.array_equal(a.data, again.data)
    src.close()


# ------------------------------------------------------------------------- timeline maths
@pytest.mark.parametrize("ppf", [0.05, 0.3, 1, 2.7, 6, 13, 40, 80])
def test_tick_steps(ppf):
    major, minor = tick_steps(ppf)
    assert major * ppf >= 56 or major == 10000
    if minor:
        assert major % minor == 0 and minor * ppf >= 6 and minor < major


def test_tick_steps_examples():
    assert tick_steps(4.3)[0] == 20          # ~250-frame clip on a 1000 px ruler -> labels every 20, like Cavalry
    assert tick_steps(60)[0] == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
