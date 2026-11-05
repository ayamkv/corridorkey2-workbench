"""App logic that needs no GPU or window: clip -> job spec, ranges, sessions, media, timeline maths."""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ckapp.app.media import (ExrOutputSource, frame_paths, open_source, probe, to_display_u8,  # noqa: E402
                             to_frame)
from ckapp.app.model import FIT_TABLE, Clip, ClipSettings, Render, fit_estimate  # noqa: E402
from ckapp.app.project import (Project, ProjectError, Recent, default_location, safe_name,  # noqa: E402
                               session_clips)
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


def test_project_round_trip(tmp_path):
    clip_file = tmp_path / "x.mp4"
    clip_file.write_bytes(b"")
    p = Project.create(tmp_path / "proj")
    c = Clip(str(clip_file), "video", 50, 25.0, 1280, 720)
    c.settings.range_mode, c.settings.frame_in, c.settings.frame_out, c.settings.despill = "custom", 3, 30, 0.36
    p.add(c)
    out_dir, _ = c.next_render_dir()
    assert out_dir == os.path.join(p.root, "renders", "x", "render_001")
    c.renders.append(Render("job1", out_dir, 3, 30, "exr", status="done",
                            outputs={"alpha": os.path.join(out_dir, "x_alpha_exr")}, label="Render 1"))
    assert p.save()
    p2 = Project.open(tmp_path / "proj")
    c2 = p2.clips[0]
    assert c2.id == c.id and c2.settings == c.settings and c2.frame_range() == (3, 30) and c2.folder == "x"
    assert c2.latest_render().outputs == c.latest_render().outputs and not c2.error
    clip_file.unlink()
    assert Project.open(tmp_path / "proj" / "project.json").clips[0].error == "missing"


def test_project_paths_are_relative_so_it_can_move(tmp_path):
    p = Project.create(tmp_path / "a")
    c = Clip(str(tmp_path / "plate.mp4"), "video", 10, 24, 64, 64)
    p.add(c)
    inside = os.path.join(p.root, "renders", "plate", "render_001")
    outside = str(tmp_path / "elsewhere" / "plate_ck2" / "render_001")     # from before projects
    c.renders += [Render("j1", inside, 0, 9, "video", outputs={"fg": os.path.join(inside, "plate_fg.mp4")}),
                  Render("j0", outside, 0, 9, "video", outputs={"fg": os.path.join(outside, "plate_fg.mp4")})]
    p.save()
    raw = json.loads((tmp_path / "a" / "project.json").read_text(encoding="utf-8"))
    r1, r0 = raw["clips"][0]["renders"]
    assert r1["out_dir"] == "renders/plate/render_001" and r1["outputs"]["fg"] == "renders/plate/render_001/plate_fg.mp4"
    assert r0["out_dir"] == outside and "base" not in raw["clips"][0]
    os.rename(tmp_path / "a", tmp_path / "b")
    moved = Project.open(tmp_path / "b")
    m1, m0 = moved.clips[0].renders
    assert m1.out_dir == os.path.join(str(tmp_path / "b"), "renders", "plate", "render_001")
    assert m1.outputs["fg"] == os.path.join(m1.out_dir, "plate_fg.mp4") and m0.out_dir == outside
    assert moved.clips[0].render_root() == os.path.join(str(tmp_path / "b"), "renders", "plate")


def test_drawn_hint_path_is_relative_so_it_moves_with_the_project(tmp_path):
    p = Project.create(tmp_path / "a")
    c = Clip(str(tmp_path / "plate.mp4"), "video", 10, 24, 64, 64)
    p.add(c)
    c.settings.hint_mode, c.settings.hint_frame = "first", 4
    c.settings.hint_path = os.path.join(c.masks_dir(), "hint_f000004.png")
    p.save()
    raw = json.loads((tmp_path / "a" / "project.json").read_text(encoding="utf-8"))
    assert raw["clips"][0]["settings"]["hint_path"] == "masks/plate/hint_f000004.png"
    os.rename(tmp_path / "a", tmp_path / "b")
    s = Project.open(tmp_path / "b").clips[0].settings
    assert s.hint_path == os.path.join(str(tmp_path / "b"), "masks", "plate", "hint_f000004.png")
    assert s.hint_frame == 4


@pytest.mark.parametrize("mode,fin,fout,frame,expect", [
    ("all", 0, -1, 40, (40, 99)),            # entire clip: from the hint frame to the end
    ("custom", 10, 60, 40, (40, 60)),        # out-point still after it: kept
    ("custom", 10, 30, 40, (40, 99)),        # out-point before it: runs to the end, never a 1-frame render
    ("custom", 10, 60, 60, (60, 60)),
    ("custom", 10, 60, 500, (99, 99))])
def test_hint_range_puts_the_in_point_on_the_hint_frame(mode, fin, fout, frame, expect):
    assert make_clip(range_mode=mode, frame_in=fin, frame_out=fout).hint_range(frame) == expect


def test_hint_mismatch_only_for_drawn_first_frame_hints():
    c = make_clip(range_mode="custom", frame_in=12, frame_out=50, hint_mode="first", hint_path="h.png",
                  hint_frame=20)
    assert c.hint_mismatch() == 20
    c.settings.frame_in = 20
    assert c.hint_mismatch() is None
    c.settings.frame_in, c.settings.hint_frame = 12, -1          # chosen file: frame unknown
    assert c.hint_mismatch() is None
    c.settings.hint_frame, c.settings.hint_mode = 20, "video"
    assert c.hint_mismatch() is None


# ------------------------------------------------------------------------- click to mask
def _session():
    from ckapp.app.masking import MaskSession
    return MaskSession("c1", 7, 160, 90, "img.png", "out.png")


def test_mask_session_edits_and_undo():
    s = _session()
    assert s.empty() and not s.stale() and not s.fresh()
    assert not s.add_point(200, 10, True) and not s.add_point(-1, 10, True)     # outside the image
    assert s.add_point(10, 20, True) and s.add_point(30, 40, False)
    assert s.points == [[10, 20, 1], [30, 40, 0]] and s.stale() and s.summary() == "1 keep, 1 remove"
    assert s.set_box(150, 80, -20, 5)                                         # any corner order, clamped
    assert s.box == [0, 5, 150, 80]
    assert not s.set_box(10, 10, 11, 50)                                      # too thin: a slip, not a box
    assert s.set_box(20, 20, 60, 60) and s.undo() and s.box == [0, 5, 150, 80]   # undo restores the old box
    assert s.clear() and s.empty() and s.mask is None and not s.stale()
    assert s.undo() and s.points and s.box                                    # Clear can be undone
    while s.undo():
        pass
    assert s.empty() and s.mask is None


def test_mask_session_keeps_only_masks_for_its_latest_edit():
    s = _session()
    s.add_point(10, 20, True)
    gen = s.gen
    m = np.zeros((90, 160), np.uint8)
    assert not s.set_mask(gen, np.zeros((10, 10), np.uint8), 0.9)             # wrong size
    s.add_point(50, 50, True)                                                 # edited while the request was out
    assert not s.set_mask(gen, m, 0.9) and s.mask is None
    assert s.set_mask(s.gen, m, 0.9) and s.fresh()
    key = s.mask_key
    assert s.mask_frame().data.shape == (90, 160, 1)
    s.add_point(60, 60, True)
    assert s.stale() and not s.fresh() and s.mask is not None                # old mask stays on screen meanwhile
    assert s.set_mask(s.gen, m.copy(), 0.8) and s.mask_key != key             # new mask, new texture key


def test_hint_file_never_overwrites(tmp_path):
    from ckapp.app.masking import hint_file
    first = hint_file(str(tmp_path), 12)
    assert os.path.basename(first) == "hint_f000012.png"
    open(first, "wb").close()
    assert os.path.basename(hint_file(str(tmp_path), 12)) == "hint_f000012_2.png"


def test_display_u8_encodes_linear_to_srgb():
    from ckapp.app.media import Frame, display_u8
    lin = Frame(np.full((2, 2, 3), 0.18, np.float16), linear=True)
    assert abs(int(display_u8(lin)[0, 0, 0]) - 118) <= 1                     # 18% grey is about 118 in sRGB
    assert display_u8(Frame(np.full((2, 2, 3), 0.5, np.float16)))[0, 0, 0] == 128
    u8 = np.full((2, 2, 3), 7, np.uint8)
    assert display_u8(Frame(u8)) is u8


def test_clip_folders_are_unique(tmp_path):
    p = Project.create(tmp_path / "p")
    a = Clip(str(tmp_path / "one" / "plate.mp4"), "video", 10, 24, 64, 64)
    b = Clip(str(tmp_path / "two" / "Plate.mp4"), "video", 10, 24, 64, 64)
    seq = Clip(str(tmp_path / "x" / "frames"), "sequence", 10, 24, 64, 64)
    seq2 = Clip(str(tmp_path / "y" / "frames"), "sequence", 10, 24, 64, 64)
    for c in (a, b, seq, seq2):
        p.add(c)
    assert [c.folder for c in (a, b, seq, seq2)] == ["plate", "Plate_2", "frames", "frames_2"]
    p.clips.remove(a)                                        # a removed clip's folder on disk stays its own
    os.makedirs(os.path.join(p.root, "renders", "plate", "render_001"))
    again = Clip(a.path, "video", 10, 24, 64, 64)
    p.add(again)
    assert again.folder == "plate_3"


@pytest.mark.parametrize("raw,expect", [("CON", "_CON"), ("nul.txt", "_nul.txt"), ("a:b*c?", "a_b_c_"),
                                        ("shot. ", "shot"), ("...", "clip")])
def test_safe_name(raw, expect):
    assert safe_name(raw) == expect


def test_newer_project_refused_and_existing_not_overwritten(tmp_path):
    p = Project.create(tmp_path / "p")
    with pytest.raises(ProjectError):
        Project.create(tmp_path / "p")
    data = json.loads(p.path.read_text(encoding="utf-8"))
    data["version"] = 99
    p.path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProjectError, match="newer version"):
        Project.open(p.path)


def test_bring_in_old_session(tmp_path):
    clip_file = tmp_path / "shot.mp4"
    clip_file.write_bytes(b"")
    old = Clip(str(clip_file), "video", 20, 24, 64, 64)
    old.renders.append(Render("j9", str(tmp_path / "shot_ck2" / "render_001"), 0, 19, "video", status="done"))
    session = tmp_path / "state" / "session.json"
    session.parent.mkdir()
    session.write_text(json.dumps({"version": 1, "clips": [dataclasses.asdict(old)]}), encoding="utf-8")
    assert len(session_clips(session)) == 1
    p = Project.create(tmp_path / "proj")
    assert p.bring_in(session) == 1
    assert not session.exists() and (session.parent / "session.migrated.json").exists()
    c = Project.open(p.path).clips[0]
    assert c.renders[0].out_dir == str(tmp_path / "shot_ck2" / "render_001")      # renders stay where they are
    assert c.renders[0].label == ""                                  # this one had no label; a labelled one:
    c.renders[0].label = "Render 1"
    assert c.next_render_dir() == (os.path.join(p.root, "renders", "shot", "render_002"), "Render 2")


def test_recent_list(tmp_path):
    r = Recent(tmp_path / "recent.json")
    for i in range(3):
        f = tmp_path / f"p{i}" / "project.json"
        f.parent.mkdir()
        f.write_text("{}")
        r.add(str(f))
    r.add(str(tmp_path / "p0" / "project.json"))
    r.last_parent = str(tmp_path)
    r.save()
    r2 = Recent(tmp_path / "recent.json")
    assert [os.path.basename(os.path.dirname(p)) for p in r2.projects] == ["p0", "p2", "p1"]
    os.remove(tmp_path / "p2" / "project.json")
    assert len(r2.existing()) == 2 and r2.last_parent == str(tmp_path)


def test_default_location_never_a_full_system_drive(tmp_path):
    docs = r"C:\Users\me\Documents"
    drives = [("C:\\", 3.0), ("D:\\", 400.0), ("E:\\", 120.0)]
    assert default_location(str(tmp_path), docs, 3.0, drives) == str(tmp_path)          # last folder used wins
    assert default_location("", docs, 3.0, drives) == os.path.join("D:\\", "CorridorKey2 Projects")
    assert default_location("", docs, 25.0, drives) == os.path.join(docs, "CorridorKey2 Projects")
    assert default_location(r"Z:\gone", docs, 3.0, drives).startswith("D:")


def test_settings_ignore_unknown_keys():
    assert ClipSettings.from_dict({"despill": 0.2, "from_the_future": 1}).despill == 0.2


# ------------------------------------------------------------------------- GPU memory guide
@pytest.mark.skipif(not os.path.isfile(os.path.join(UPSTREAM, "README.md")), reason="upstream repo not found")
def test_fit_table_matches_upstream_readme():
    import re
    text = open(os.path.join(UPSTREAM, "README.md"), encoding="utf-8").read()
    rows = {}
    for m in re.finditer(r"^\|\s*(\d+) GB\s*\|(.+)\|\s*$", text, re.M):
        rows[int(m.group(1))] = [c.strip() for c in m.group(2).split("|")]
    assert rows == FIT_TABLE
    assert re.search(r"^\| GPU memory \| 720p \| 1080p \| 1440p \| 4K \|", text, re.M)


@pytest.mark.parametrize("w,h,mb,expect,warn", [
    (1920, 1080, 4096, "1080p with 4 GB of GPU memory: Auto picks about 2/1 low-VRAM", False),
    (1920, 1080, 3800, "1080p with 4 GB of GPU memory", False),                     # reports a little under 4 GiB
    (3840, 2160, 4096, "not enough memory", True),
    (1280, 536, 6144, "720p with 6 GB of GPU memory: Auto picks about 24/12 low-VRAM", False),
    (2048, 1080, 8192, "1440p with 8 GB of GPU memory", False),                     # rounds up to the next column
    (4096, 2160, 24576, "Larger than 4K", True),
    (1920, 1080, 81920, "1080p with 48 GB or more of GPU memory: Auto picks about 80/40", False),
    (1920, 1080, 2048, "Below the smallest card", True)])
def test_fit_estimate(w, h, mb, expect, warn):
    text, warning = fit_estimate(w, h, mb)
    assert expect in text and warning == warn


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
