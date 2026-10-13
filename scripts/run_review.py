"""Entrypoint nightly review."""
import sys
sys.path.insert(0, ".")
from src.review import write_report

if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "config/config.yaml"
    write_report(cfg)
