"""Job specs, the infer command line, progress parsing and the single-GPU job queue.

Qt-free and torch-free, so it is unit-testable anywhere.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

OUTPUT_KEYS = ("alpha", "fg", "checker", "cutout")
HINT_MODES = ("none", "first", "video")
# Video encoding (infer.py --ffmpeg_codec/--pix_fmt/--preset/--crf/--bitrate). The cutout output ignores
# these: upstream always writes it as ProRes 4444 with alpha.
VIDEO_CODECS = ("libx264", "libx265")
PIX_FMTS = ("yuv444p10le", "yuv422p10le", "yuv420p10le", "yuv420p")
PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
_BITRATE = re.compile(r"^\d+(\.\d+)?[kKmM]?$")


@dataclass
class JobSpec:
    """Everything one render needs. Mirrors infer.py flags; defaults match infer.py."""
    input: str
    output_dir: str
    name: str = ""                       # display name (defaults to the input file name)
    frame_in: Optional[int] = None       # 0-based, inclusive; None = from the start
    frame_out: Optional[int] = None      # None = to the end
    hint_mode: str = "none"              # none | first | video
    hint_path: str = ""
    hint_quality: float = 0.95
    carry_hint: bool = True
    carry_hint_quality: float = 0.95
    outputs: list = field(default_factory=lambda: ["alpha", "fg"])
    despill: float = 0.5
    output_format: str = "video"         # video | exr
    exr_dtype: str = "half"
    cutout_linear: bool = False
    frame_dir_linear: bool = False
    frame_dir_fps: float = 24.0
    auto_vram: bool = True
    low_vram: bool = False
    hann_chunk: int = 48
    hann_stride: int = 24
    video_codec: str = "libx264"
    pix_fmt: str = "yuv444p10le"
    crf: int = 12                        # constant quality; lower = better, bigger
    bitrate: str = ""                    # e.g. "40M"; when set it replaces crf
    preset: str = "medium"
    ffmpeg_threads: int = 2
    project: str = ""                    # project.json this render belongs to (bookkeeping only)

    def validate(self) -> None:
        if not self.input or not os.path.exists(self.input):
            raise ValueError(f"input not found: {self.input}")
        if not self.output_dir:
            raise ValueError("output_dir is required")
        if self.hint_mode not in HINT_MODES:
            raise ValueError(f"hint_mode must be one of {HINT_MODES}")
        if self.hint_mode != "none" and not os.path.exists(self.hint_path):
            raise ValueError(f"hint not found: {self.hint_path}")
        bad = [o for o in self.outputs if o not in OUTPUT_KEYS]
        if bad or not self.outputs:
            raise ValueError(f"outputs must be a non-empty subset of {OUTPUT_KEYS}")
        if self.output_format not in ("video", "exr"):
            raise ValueError("output_format must be video or exr")
        if self.exr_dtype not in ("half", "float"):
            raise ValueError("exr_dtype must be half or float")
        if not 0.0 <= self.despill <= 1.0:
            raise ValueError("despill must be within 0..1")
        for q in (self.hint_quality, self.carry_hint_quality):
            if not 0.0 <= q <= 1.0:
                raise ValueError("hint qualities must be within 0..1")
        if self.frame_in is not None and self.frame_in < 0:
            raise ValueError("frame_in must be >= 0")
        if self.frame_out is not None and self.frame_out < (self.frame_in or 0):
            raise ValueError("frame_out must be >= frame_in")
        if not self.auto_vram and (self.hann_chunk < 1 or self.hann_stride < 1):
            raise ValueError("hann_chunk and hann_stride must be >= 1")
        if self.video_codec not in VIDEO_CODECS:
            raise ValueError(f"video_codec must be one of {VIDEO_CODECS}")
        if self.pix_fmt not in PIX_FMTS:
            raise ValueError(f"pix_fmt must be one of {PIX_FMTS}")
        if self.preset not in PRESETS:
            raise ValueError(f"preset must be one of {PRESETS}")
        if not 0 <= int(self.crf) <= 51:
            raise ValueError("crf must be within 0..51")
        if self.bitrate and not _BITRATE.match(self.bitrate):
            raise ValueError("bitrate must look like 40M, 8000k or 25000000")
        if not 1 <= int(self.ffmpeg_threads) <= 64:
            raise ValueError("ffmpeg_threads must be within 1..64")

    @classmethod
    def from_dict(cls, d: dict) -> "JobSpec":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def build_command(spec: JobSpec, *, ck_python: str, ck_root: str, cache_dir: str,
                  ffmpeg: str = "") -> list[str]:
    """argv for ck_run.py -> infer.py. A plain list: never passed through a shell."""
    cmd = [ck_python, str(Path(__file__).with_name("ck_run.py")), "--ck-root", ck_root]
    if spec.frame_in is not None:
        cmd += ["--frame-in", str(spec.frame_in)]
    if spec.frame_out is not None:
        cmd += ["--frame-out", str(spec.frame_out)]
    cmd += ["--", "--input", spec.input, "--output_dir", spec.output_dir]

    if spec.hint_mode == "first":
        cmd += ["--hint_first_frame", spec.hint_path, "--hint_quality", f"{spec.hint_quality:g}",
                "--carry_hint_quality", f"{spec.carry_hint_quality:g}"]
    elif spec.hint_mode == "video":
        cmd += ["--hint_video", spec.hint_path, "--hint_quality", f"{spec.hint_quality:g}"]
        if spec.carry_hint:
            cmd += ["--carry_hint_quality", f"{spec.carry_hint_quality:g}"]
        else:
            cmd.append("--no_carry_hint")

    cmd += ["--outputs", *[o for o in OUTPUT_KEYS if o in spec.outputs]]
    cmd += ["--despill_strength", f"{spec.despill:g}"]
    cmd += ["--output_format", spec.output_format]
    if spec.output_format == "exr":
        cmd += ["--exr_dtype", spec.exr_dtype]
    else:
        if spec.cutout_linear and "cutout" in spec.outputs:
            cmd.append("--cutout_linear")
        cmd += ["--ffmpeg_codec", spec.video_codec, "--pix_fmt", spec.pix_fmt, "--preset", spec.preset,
                "--ffmpeg_threads", str(int(spec.ffmpeg_threads))]
        cmd += ["--bitrate", spec.bitrate] if spec.bitrate else ["--crf", str(int(spec.crf))]
    if os.path.isdir(spec.input):
        cmd += ["--frame_dir_fps", f"{spec.frame_dir_fps:g}"]
        if spec.frame_dir_linear:
            cmd.append("--frame_dir_linear")
    if ffmpeg:
        cmd += ["--ffmpeg_bin", ffmpeg]

    # Memory: no flags = infer.py picks a profile from free VRAM per clip.
    if spec.low_vram:
        cmd.append("--low_vram")
    if not spec.auto_vram:
        cmd += ["--hann_chunk", str(spec.hann_chunk), "--hann_stride", str(spec.hann_stride)]
    cmd += ["--temp_dir", str(Path(cache_dir) / "staging")]
    return cmd


# --------------------------------------------------------------------------- progress
# (pattern, stage label, fraction at that point). "window i/N" and "written k/T"
# interpolate inside their bands.
_STAGES = [
    (re.compile(r"^Loading CorridorKey"), "Loading model", 0.02),
    (re.compile(r"loaded weights"), "Loading model", 0.05),
    (re.compile(r"^\s*probed \d+ frames"), "Reading clip", 0.06),
    (re.compile(r"Auto VRAM:"), "Choosing memory profile", 0.07),
    (re.compile(r"RVM continuous prepass"), "Motion prepass", 0.08),
    (re.compile(r"frozen VFM prepass"), "Feature prepass", 0.15),
    (re.compile(r"Hann stage1:"), "Keying", 0.25),
]
_WINDOW = re.compile(r"^\s*window (\d+)/(\d+)")
_WRITTEN = re.compile(r"\[ck\] written (\d+)/(\d+)")
_RANGE = re.compile(r"range: frames (\d+)-(\d+) \((\d+) frames\)")
_KEY_BAND = (0.25, 0.60)
_WRITE_BAND = (0.60, 0.99)


class ProgressParser:
    def __init__(self) -> None:
        self.fraction = 0.0
        self.stage = "Starting"
        self.frames_total = 0
        self.warnings: list[str] = []

    def feed(self, line: str) -> bool:
        """Returns True when fraction or stage changed."""
        before = (self.fraction, self.stage)
        frac, stage = None, None
        if m := _WINDOW.match(line):
            i, n = int(m[1]), max(1, int(m[2]))
            lo, hi = _KEY_BAND
            frac, stage = lo + (hi - lo) * (i - 1) / n, f"Keying (window {i}/{n})"
        elif m := _WRITTEN.search(line):
            k, t = int(m[1]), max(1, int(m[2]))
            self.frames_total = t
            lo, hi = _WRITE_BAND
            frac, stage = lo + (hi - lo) * k / t, f"Writing frames {k}/{t}"
        elif m := _RANGE.search(line):
            self.frames_total = int(m[3])
        elif "[WARNING]" in line:
            self.warnings.append(line.strip())
        else:
            for rx, label, f in _STAGES:
                if rx.search(line):
                    frac, stage = f, label
                    break
        if frac is not None:
            self.fraction = max(self.fraction, frac)     # never goes backwards
            self.stage = stage
        return (self.fraction, self.stage) != before


# --------------------------------------------------------------------------- jobs
HELD, QUEUED, RUNNING, DONE, ERROR, CANCELLED, INTERRUPTED = (
    "held", "queued", "running", "done", "error", "cancelled", "interrupted")
FINISHED = (DONE, ERROR, CANCELLED, INTERRUPTED)
PENDING = (HELD, QUEUED, RUNNING)

_ids = itertools.count(1)


@dataclass
class Job:
    spec: JobSpec
    id: str = field(default_factory=lambda: f"{time.strftime('%Y%m%d-%H%M%S')}-{next(_ids)}")
    status: str = QUEUED
    fraction: float = 0.0
    stage: str = "Queued"
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0
    error: str = ""
    warnings: list = field(default_factory=list)
    outputs: dict = field(default_factory=dict)      # key -> file or EXR folder
    log: list = field(default_factory=list)

    def eta_seconds(self) -> Optional[float]:
        if self.status != RUNNING or self.fraction < 0.08 or not self.started:
            return None
        elapsed = time.time() - self.started
        return elapsed / self.fraction * (1.0 - self.fraction)

    def to_dict(self, with_log: bool = False) -> dict:
        d = {
            "id": self.id, "status": self.status, "fraction": round(self.fraction, 4),
            "stage": self.stage, "created": self.created, "started": self.started,
            "finished": self.finished, "error": self.error, "warnings": self.warnings,
            "outputs": self.outputs, "eta": self.eta_seconds(), "spec": asdict(self.spec),
            "name": self.spec.name or os.path.basename(self.spec.input.rstrip("/\\")),
        }
        if with_log:
            d["log"] = list(self.log)
        return d


def discover_outputs(out_dir: str) -> dict:
    """Map output key -> path for whatever infer.py wrote into a render folder."""
    found: dict = {}
    try:
        names = sorted(os.listdir(out_dir))
    except OSError:
        return found
    for n in names:
        p = os.path.join(out_dir, n)
        stem = n[:-4] if n.lower().endswith("_exr") else os.path.splitext(n)[0]
        if stem.endswith("_alpha"):
            found["alpha"] = p
        elif stem.endswith("_fg"):
            found["fg"] = p
        elif "_checker_comp_despill" in stem:
            found["checker"] = p
        elif stem.endswith("_cutout"):
            found["cutout"] = p
    return found


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop the child and everything it started (infer.py spawns ffmpeg encoders)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()


class JobQueue:
    """One GPU, one job at a time. Thread-based; callbacks fire on the worker thread."""

    LOG_LIMIT = 4000

    def __init__(self, *, ck_python: str, ck_root: str, cache_dir: str, ffmpeg: str = "",
                 history_path: Optional[Path] = None,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 command_builder: Callable[..., list[str]] = build_command,
                 before_run: Optional[Callable[[], None]] = None) -> None:
        self.ck_python, self.ck_root, self.cache_dir, self.ffmpeg = ck_python, ck_root, cache_dir, ffmpeg
        self.history_path = history_path
        self.on_event = on_event or (lambda kind, data: None)
        self.command_builder = command_builder
        self.before_run = before_run or (lambda: None)     # e.g. free the GPU from the mask model
        self.jobs: list[Job] = []
        self.current: Optional[Job] = None
        self._proc: Optional[subprocess.Popen] = None
        self._cancel = False
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = False
        self._load_history()
        self._thread = threading.Thread(target=self._worker, name="ck-jobs", daemon=True)
        self._thread.start()

    # -- public -----------------------------------------------------------------------------
    def submit(self, spec: JobSpec, hold: bool = False) -> Job:
        """`hold`: park the job until start() (Add to queue) instead of running it when the GPU is free."""
        spec.validate()
        job = Job(spec)
        if hold:
            job.status, job.stage = HELD, "Waiting for Start"
        with self._lock:
            self.jobs.append(job)
        self._emit(job)
        self._save_history()
        self._wake.set()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return next((j for j in self.jobs if j.id == job_id), None)

    def list(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in self.jobs]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self.get(job_id)
            if job is None:
                return False
            if job.status in (HELD, QUEUED):
                self._finish(job, CANCELLED)
                return True
            if job.status == RUNNING and self._proc is not None:
                self._cancel = True
                kill_tree(self._proc)
                return True
            return False

    def start(self, job_id: Optional[str] = None) -> int:
        """Release one held job, or all of them when job_id is None. Returns how many."""
        with self._lock:
            held = [j for j in self.jobs if j.status == HELD and (job_id is None or j.id == job_id)]
            for j in held:
                j.status, j.stage = QUEUED, "Queued"
        for j in held:
            self._emit(j)
        if held:
            self._save_history()
            self._wake.set()
        return len(held)

    def remove(self, job_id: str) -> bool:
        with self._lock:
            job = self.get(job_id)
            if job is None or job.status in PENDING:
                return False
            self.jobs.remove(job)
        self.on_event("removed", {"id": job_id})
        self._save_history()
        return True

    def busy(self) -> bool:
        with self._lock:
            return self.current is not None or any(j.status == QUEUED for j in self.jobs)

    def shutdown(self) -> None:
        self._stop = True
        with self._lock:
            if self._proc is not None:
                self._cancel = True
                kill_tree(self._proc)
        self._wake.set()
        self._thread.join(timeout=10)

    # -- worker -----------------------------------------------------------------------------
    def _next(self) -> Optional[Job]:
        with self._lock:
            return next((j for j in self.jobs if j.status == QUEUED), None)

    def _worker(self) -> None:
        while not self._stop:
            job = self._next()
            if job is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        parser = ProgressParser()
        try:
            self.before_run()
        except Exception:  # never let a side service block renders
            pass
        try:
            os.makedirs(job.spec.output_dir, exist_ok=True)
            os.makedirs(os.path.join(self.cache_dir, "staging"), exist_ok=True)
            cmd = self.command_builder(job.spec, ck_python=self.ck_python, ck_root=self.ck_root,
                                       cache_dir=self.cache_dir, ffmpeg=self.ffmpeg)
        except Exception as e:  # bad paths etc.: fail the job, keep the queue alive
            with self._lock:
                job.error = str(e)
                self._finish(job, ERROR)
            return
        env = dict(os.environ)
        env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONUNBUFFERED": "1",
                    "PYTHONIOENCODING": "utf-8", "TMP": self.cache_dir, "TEMP": self.cache_dir,
                    "TMPDIR": self.cache_dir})
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
        with self._lock:
            if job.status != QUEUED:          # cancelled while we were preparing
                return
            self._cancel = False
            job.status, job.started, job.stage = RUNNING, time.time(), "Starting"
            self.current = job
            self._log(job, "$ " + " ".join(f'"{a}"' if " " in a else a for a in cmd))
            try:
                self._proc = subprocess.Popen(
                    cmd, cwd=self.ck_root or None, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags,
                    start_new_session=(os.name != "nt"))
            except OSError as e:
                job.error = f"could not start {cmd[0]}: {e}"
                self._finish(job, ERROR)
                return
        self._emit(job)
        proc = self._proc
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line.strip():
                continue
            with self._lock:
                self._log(job, line)
                if parser.feed(line):
                    job.fraction, job.stage = parser.fraction, parser.stage
                    job.warnings = list(parser.warnings)
                    changed = True
                else:
                    changed = False
            if changed:
                self._emit(job)
        code = proc.wait()
        with self._lock:
            self._proc = None
            job.outputs = discover_outputs(job.spec.output_dir)
            if self._cancel:
                self._finish(job, CANCELLED)
            elif code == 0:
                job.fraction = 1.0
                self._finish(job, DONE)
            else:
                tail = [l for l in job.log[-15:] if l.strip() and not l.startswith("$")]
                job.error = next((l for l in reversed(tail) if "Error" in l or "error" in l),
                                 tail[-1] if tail else f"exit code {code}")
                self._finish(job, ERROR)

    # -- helpers ----------------------------------------------------------------------------
    def _log(self, job: Job, line: str) -> None:
        job.log.append(line)
        if len(job.log) > self.LOG_LIMIT:
            del job.log[: self.LOG_LIMIT // 4]
        self.on_event("log", {"id": job.id, "line": line})

    def _finish(self, job: Job, status: str) -> None:
        job.status, job.finished = status, time.time()
        job.stage = {DONE: "Done", ERROR: "Failed", CANCELLED: "Cancelled"}.get(status, status)
        if self.current is job:
            self.current = None
        self._emit(job)
        self._save_history()

    def _emit(self, job: Job) -> None:
        self.on_event("job", job.to_dict())

    def _save_history(self) -> None:
        if self.history_path is None:
            return
        with self._lock:
            data = [j.to_dict(with_log=False) for j in self.jobs]
        tmp = self.history_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self.history_path)
        except OSError:
            pass

    def _load_history(self) -> None:
        if self.history_path is None or not self.history_path.is_file():
            return
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for d in data:
            try:
                job = Job(JobSpec.from_dict(d["spec"]), id=d["id"], status=d["status"],
                          fraction=d.get("fraction", 0.0), stage=d.get("stage", ""),
                          created=d.get("created", 0.0), started=d.get("started", 0.0),
                          finished=d.get("finished", 0.0), error=d.get("error", ""),
                          warnings=d.get("warnings", []), outputs=d.get("outputs", {}))
            except (KeyError, TypeError):
                continue
            if job.status in (QUEUED, RUNNING):     # the engine stopped while these were pending
                job.status, job.stage = INTERRUPTED, "Interrupted"
            # held jobs stay held: they were waiting for Start, not running
            self.jobs.append(job)
