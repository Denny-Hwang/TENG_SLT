# Protocol parser changes

## 2026-10-16 - Session logging extensions - [UNCONFIRMED]

Added fixed-size SD records 0x16 displacement, 0x17 current stats and 0x18 session
metadata, returned as displacement/current_stats/session_meta and optionally
exported through the legacy CSV API. Legacy BIN compatibility tests pass.