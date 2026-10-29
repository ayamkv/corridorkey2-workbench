import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
collect_ignore = ["fake_ck_run.py", "test_seek_accuracy.py"]   # helper / run in the CorridorKey venv
