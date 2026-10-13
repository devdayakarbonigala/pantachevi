import os

# Tests must never depend on the network or on today's real weather.
os.environ.setdefault("PANTACHEVI_WEATHER", "stub")
