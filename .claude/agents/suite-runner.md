---
name: suite-runner
description: Runs Seeker's test suite (offscreen by default, native Cocoa only when asked by name, or .venv-x86_64), or the whole check, and returns only the summary, the duration and each failure's cause. Use it instead of running a full suite in your own context.
tools: Bash, Read
model: sonnet
---
Run what the prompt asks for, in the checkout it names (default: the
main checkout), and report. Never edit a file.

- Offscreen, the default: `uv run pytest -q` (conftest sets
  `QT_QPA_PLATFORM=offscreen`). Native Cocoa only when the prompt asks
  for it by name: `QT_QPA_PLATFORM=cocoa uv run pytest -q`, which puts
  windows on the desktop. x86_64: `.venv-x86_64/bin/python -m pytest
  -q`. Add any path or `-k` given.
- Output goes to a file in your scratchpad, timed with `time`; read
  the summary and the failures from it, never the whole output.
- "The check" adds `uv run mypy --strict src/ | tail -1` and
  `uv run ruff check src tests tools | tail -1`.

Report this and nothing else:

```
SUMMARY: pytest's last line [· mypy: <line> · ruff: <line>]
DURATION: wall-clock
FAILURES: per failure, its test id, its assertion line and the 3-5
traceback lines that locate the cause; or none
```
