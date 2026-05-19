"""
Vaarta-worker entrypoint dispatcher.

Usage:
    python main.py migrate  # apply pending SQL migrations from migrations/
    python main.py ingest   # one-shot: fetch -> dedupe -> cluster -> enqueue
    python main.py llm      # long-running: drain summarization queue
    python main.py trend    # one-shot: recompute cluster importance scores

Typical deployment:
    one-time / on schema changes:  python main.py migrate
    cron: */15 * * * *   python main.py ingest
    cron: */30 * * * *   python main.py trend
    daemon (always on)   python main.py llm
"""
from __future__ import annotations
import sys

USAGE = __doc__


def main() -> None:
    if len(sys.argv) != 2:
        print(USAGE)
        sys.exit(1)

    name = sys.argv[1]
    if name == "migrate":
        from workers.migrate import run
    elif name == "ingest":
        from workers.ingest import run
    elif name == "llm":
        from workers.llm import run
    elif name == "trend":
        from workers.trend import run
    else:
        print(f"Unknown worker: {name!r}\n{USAGE}")
        sys.exit(1)

    run()


if __name__ == "__main__":
    main()
