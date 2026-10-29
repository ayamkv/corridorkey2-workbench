"""Engine tests: command line, progress parsing, job queue, HTTP API. No GPU needed."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ckapp.engine.jobs import (CANCELLED, DONE, ERROR, INTERRUPTED, JobQueue, JobSpec, ProgressParser,
                               build_command, discover_outputs)

FAKE = str(Path(__file__).with_name("fake_ck_run.py"))


@pytest.fixture
def clip(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"x")
    return str(p)


def fake_builder(mode, pidfile=""):
    def build(spec, **kw):
        return [sys.executable, FAKE, spec.output_dir, mode, pidfile]
    return build


def wait_for(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------------- command line
def test_command_default(clip, tmp_path):
    spec = JobSpec(input=clip, output_dir=str(tmp_path / "out"))
    cmd = build_command(spec, ck_python="py", ck_root="R", cache_dir=str(tmp_path / "c"))
    assert cmd[:4] == ["py", cmd[1], "--ck-root", "R"] and cmd[1].endswith("ck_run.py")
    rest = cmd[cmd.index("--") + 1:]
    assert rest[:4] == ["--input", clip, "--output_dir", str(tmp_path / "out")]
    assert rest[rest.index("--outputs") + 1: rest.index("--outputs") + 3] == ["alpha", "fg"]
    assert "--low_vram" not in rest and "--hann_chunk" not in rest      # auto VRAM
    assert "--frame-in" not in cmd and "--num_frames" not in rest
    assert rest[rest.index("--temp_dir") + 1] == str(tmp_path / "c" / "staging")


def test_command_range_hint_manual_memory(clip, tmp_path):
    hint = tmp_path / "h.png"
    hint.write_bytes(b"x")
    spec = JobSpec(input=clip, output_dir="o", frame_in=10, frame_out=99, hint_mode="first",
                   hint_path=str(hint), hint_quality=0.75, outputs=["cutout", "alpha"],
                   output_format="exr", exr_dtype="float", cutout_linear=True,
                   auto_vram=False, low_vram=True, hann_chunk=8, hann_stride=4, despill=0.36)
    cmd = build_command(spec, ck_python="py", ck_root="R", cache_dir="C")
    head = cmd[: cmd.index("--")]
    assert head[-4:] == ["--frame-in", "10", "--frame-out", "99"]
    rest = cmd[cmd.index("--") + 1:]
    assert rest[rest.index("--hint_first_frame") + 1] == str(hint)
    assert rest[rest.index("--hint_quality") + 1] == "0.75"
    assert rest[rest.index("--outputs") + 1: rest.index("--outputs") + 3] == ["alpha", "cutout"]
    assert rest[rest.index("--despill_strength") + 1] == "0.36"
    assert rest[rest.index("--exr_dtype") + 1] == "float"
    assert "--cutout_linear" not in rest                                   # EXR is always linear
    assert "--low_vram" in rest and rest[rest.index("--hann_chunk") + 1] == "8"


def test_command_hint_video_no_carry(clip, tmp_path):
    hint = tmp_path / "h.mp4"
    hint.write_bytes(b"x")
    spec = JobSpec(input=clip, output_dir="o", hint_mode="video", hint_path=str(hint), carry_hint=False)
    rest = build_command(spec, ck_python="py", ck_root="R", cache_dir="C")
    assert "--hint_video" in rest and "--no_carry_hint" in rest and "--carry_hint_quality" not in rest


def test_command_video_encoding(clip, tmp_path):
    rest = build_command(JobSpec(input=clip, output_dir="o"), ck_python="py", ck_root="R", cache_dir="C")
    flag = lambda r, f: r[r.index(f) + 1]                                    # noqa: E731
    # defaults are passed explicitly and match infer.py's own defaults
    assert (flag(rest, "--ffmpeg_codec"), flag(rest, "--pix_fmt"), flag(rest, "--preset"),
            flag(rest, "--crf"), flag(rest, "--ffmpeg_threads")) == ("libx264", "yuv444p10le", "medium", "12", "2")
    assert "--bitrate" not in rest
    spec = JobSpec(input=clip, output_dir="o", video_codec="libx265", pix_fmt="yuv420p", preset="slow",
                   bitrate="40M")
    rest = build_command(spec, ck_python="py", ck_root="R", cache_dir="C")
    assert flag(rest, "--ffmpeg_codec") == "libx265" and flag(rest, "--bitrate") == "40M" and "--crf" not in rest
    rest = build_command(JobSpec(input=clip, output_dir="o", output_format="exr"),
                         ck_python="py", ck_root="R", cache_dir="C")
    assert "--ffmpeg_codec" not in rest and "--crf" not in rest              # EXR: no video encoding


def test_infer_defaults_match_spec():
    """Our 'defaults' must be upstream's real defaults, or the UI would mislabel them."""
    src = (Path(__file__).resolve().parents[2] / "CorridorKey2.0" / "infer.py")
    if not src.is_file():
        pytest.skip("upstream clone not found")
    text = src.read_text(encoding="utf-8")
    s = JobSpec(input="x", output_dir="o")
    for flag, value in (("--ffmpeg_codec", f'"{s.video_codec}"'), ("--crf", str(s.crf)),
                        ("--preset", f'"{s.preset}"'), ("--pix_fmt", f'"{s.pix_fmt}"'),
                        ("--ffmpeg_threads", str(s.ffmpeg_threads))):
        line = next(ln for ln in text.splitlines() if f'"{flag}"' in ln)
        assert f"default={value}" in line, (flag, line)


@pytest.mark.parametrize("bad", [
    {"outputs": []}, {"outputs": ["matte"]}, {"despill": 1.5}, {"hint_mode": "first", "hint_path": "nope.png"},
    {"frame_in": 5, "frame_out": 2}, {"frame_in": -1}, {"output_format": "gif"},
    {"video_codec": "prores"}, {"pix_fmt": "rgb24"}, {"crf": 60}, {"bitrate": "fast"}, {"preset": "turbo"},
])
def test_spec_validation(clip, bad):
    with pytest.raises(ValueError):
        JobSpec(input=clip, output_dir="o", **bad).validate()


# ------------------------------------------------------------------------- progress
def test_progress_parser_monotonic():
    p = ProgressParser()
    fracs = []
    for line in open(FAKE, encoding="utf-8").read().split("lines = [")[1].split("]")[0].splitlines():
        line = line.strip().strip(",").strip('"')
        if line:
            p.feed(line)
            fracs.append(p.fraction)
    for k in (4, 8, 10):
        p.feed(f"  [ck] written {k}/10")
        fracs.append(p.fraction)
    assert fracs == sorted(fracs)
    assert p.frames_total == 10 and p.stage == "Writing frames 10/10" and 0.98 < p.fraction < 1.0
    assert not p.feed("      window 1/2 [0:8]") or p.fraction == fracs[-1]       # never goes backwards


def test_discover_outputs(tmp_path):
    for n in ("c_alpha.mp4", "c_fg.mp4", "c_checker_comp_despill036.mp4", "c_cutout.mov", "c_settings.txt"):
        (tmp_path / n).write_bytes(b"")
    (tmp_path / "c_alpha_exr").mkdir()
    out = discover_outputs(str(tmp_path))
    assert set(out) == {"alpha", "fg", "checker", "cutout"}


# ------------------------------------------------------------------------- queue
def make_queue(tmp_path, mode, pidfile="", history=None):
    events = []
    q = JobQueue(ck_python=sys.executable, ck_root=str(tmp_path), cache_dir=str(tmp_path / "cache"),
                 history_path=history, on_event=lambda k, d: events.append((k, d)),
                 command_builder=fake_builder(mode, pidfile))
    return q, events


def test_queue_runs_job_to_done(clip, tmp_path):
    q, events = make_queue(tmp_path, "ok")
    try:
        job = q.submit(JobSpec(input=clip, output_dir=str(tmp_path / "out")))
        assert wait_for(lambda: job.status == DONE)
        assert job.fraction == 1.0 and set(job.outputs) == {"alpha", "fg", "checker"}
        fr = [d["fraction"] for k, d in events if k == "job"]
        assert fr == sorted(fr) and len(fr) > 5
        assert any(k == "log" and "window 2/2" in d["line"] for k, d in events)
    finally:
        q.shutdown()


def test_queue_reports_error(clip, tmp_path):
    q, _ = make_queue(tmp_path, "fail")
    try:
        job = q.submit(JobSpec(input=clip, output_dir=str(tmp_path / "out")))
        assert wait_for(lambda: job.status == ERROR)
        assert "out of memory" in job.error
    finally:
        q.shutdown()


def test_cancel_kills_whole_tree(clip, tmp_path):
    pidfile = str(tmp_path / "child.pid")
    q, _ = make_queue(tmp_path, "hang", pidfile)
    try:
        job = q.submit(JobSpec(input=clip, output_dir=str(tmp_path / "out")))
        queued = q.submit(JobSpec(input=clip, output_dir=str(tmp_path / "out2")))
        assert wait_for(lambda: os.path.exists(pidfile) and os.path.getsize(pidfile) > 0)
        child = int(open(pidfile).read())
        assert pid_alive(child)
        assert q.cancel(queued.id) and queued.status == CANCELLED
        assert q.cancel(job.id)
        assert wait_for(lambda: job.status == CANCELLED)
        assert wait_for(lambda: not pid_alive(child), timeout=10), "grandchild survived cancel"
    finally:
        q.shutdown()


def test_history_marks_unfinished_interrupted(clip, tmp_path):
    hist = tmp_path / "jobs.json"
    q, _ = make_queue(tmp_path, "hang", str(tmp_path / "p.pid"), history=hist)
    job = q.submit(JobSpec(input=clip, output_dir=str(tmp_path / "out")))
    assert wait_for(lambda: job.status == "running")
    q._save_history()
    q2 = JobQueue.__new__(JobQueue)              # load history without starting a worker
    q2.history_path, q2.jobs = hist, []
    q2._load_history()
    q.shutdown()
    assert q2.jobs[0].id == job.id and q2.jobs[0].status == INTERRUPTED


# ------------------------------------------------------------------------- HTTP API
def test_api(clip, tmp_path):
    from fastapi.testclient import TestClient
    from ckapp.engine.server import EventBus, create_app

    bus = EventBus()
    q = JobQueue(ck_python=sys.executable, ck_root=str(tmp_path), cache_dir=str(tmp_path / "cache"),
                 on_event=bus.publish, command_builder=fake_builder("ok"))
    try:
        c = TestClient(create_app(q, bus, "tok"))
        assert c.get("/health").status_code == 401
        assert c.get("/health", headers={"X-CK-Token": "wrong"}).status_code == 401
        h = {"X-CK-Token": "tok"}
        assert c.get("/health", headers=h).json()["ok"]
        assert c.post("/jobs", json={"input": "missing.mp4", "output_dir": "o"}, headers=h).status_code == 400
        r = c.post("/jobs", json={"input": clip, "output_dir": str(tmp_path / "out"), "frame_in": 5}, headers=h)
        assert r.status_code == 201
        jid = r.json()["id"]
        assert wait_for(lambda: c.get(f"/jobs/{jid}", headers=h).json()["status"] == DONE)
        full = c.get(f"/jobs/{jid}?log=true", headers=h).json()
        assert any("window 2/2" in l for l in full["log"]) and full["spec"]["frame_in"] == 5
        assert c.post(f"/jobs/{jid}/cancel", headers=h).status_code == 409
        assert c.delete(f"/jobs/{jid}", headers=h).json()["ok"]
        assert c.get("/jobs", headers=h).json() == []
        assert "disk" in c.get("/system", headers=h).json()
    finally:
        q.shutdown()
