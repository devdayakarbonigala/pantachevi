"""Re-date the demo field (98 days after sowing, last sprayed 6 days ago).

  python -m pantachevi.reset_demo

Needed because the demo field is stored: with Postgres its dates stay fixed
while real time moves on. Run this before recording the demo.
"""

from .store import get_store

if __name__ == "__main__":
    get_store().reset_demo()
    print("demo-1 reset: day 98 after sowing, last sprayed 6 days ago")
