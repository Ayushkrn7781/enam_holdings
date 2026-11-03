"""python -m finn.seed  — (re)build the clearly-labelled illustrative demo dataset."""
import logging

from .db import init_db, session_scope
from . import demo

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    init_db()
    with session_scope() as s:
        print(demo.reset(s))
