"""Validate and stage user overrides without creating persistent preferences."""
import importlib.util
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("oll_model_store", root / "open_law_lens/_model_store.py")
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)
try:
    settings = store.read_ordinary(Path(sys.argv[1]))
except FileNotFoundError:
    settings = {}
store.save_ordinary(Path(sys.argv[2]), dict(settings))
