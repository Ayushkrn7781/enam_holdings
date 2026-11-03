"""python -m finn.seed: create tables and build the illustrative demo dataset."""
from __future__ import annotations

import json

from . import demo
from .db import init_db, session_scope


def main() -> None:
    init_db()
    with session_scope() as s:
        print(json.dumps(demo.reset(s), indent=2))


if __name__ == "__main__":
    main()
