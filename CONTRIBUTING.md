# Contributing to Yale Smart Alarm CE

Thanks for your interest in contributing.

## Development Setup

```bash
git clone https://github.com/hiall-fyi/yale_smart_alarm_ce.git
cd yale_smart_alarm_ce
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

To try a change in Home Assistant, copy `custom_components/yale_smart_alarm_ce/` into your HA config's `custom_components/` directory and restart.

## Checks

```bash
ruff check custom_components
mypy custom_components/yale_smart_alarm_ce --strict
```

The ruff and mypy settings live in `pyproject.toml`, which isn't part of this repository (see the comment at the top of `requirements-dev.txt`), so on a fresh clone both tools use their defaults and will report more than the maintainer sees. The test suite isn't in the repository either. If you open a pull request, say in the description how you checked the change (a Home Assistant version, the hardware you tried it on, and what you did), and the maintainer will add the matching tests.

## Project Structure

Everything lives under `custom_components/yale_smart_alarm_ce/`, roughly grouped as:

- **Platform entities**: `alarm_control_panel.py`, `binary_sensor.py`, `lock.py`, `select.py`, `sensor.py`, `switch.py`
- **Setup and coordination**: `__init__.py`, `coordinator.py`, `config_flow.py`, `entity.py`
- **Yale cloud access**: `api.py`, `error_handler.py`, `repair_helpers.py`
- **Support**: `diagnostics.py`, `const.py`

## Pull Request Guidelines

- Keep PRs focused on a single change.
- Run `ruff check` and `mypy` before submitting.
- Update `CHANGELOG.md` with your change, under the current unreleased section.
- No ticket or issue numbers in source comments, docstrings or log strings. The CHANGELOG and the PR description are where those belong.

## Code Style

- `from __future__ import annotations` at the top of each module.
- Lazy logging (`_LOGGER.debug("...%s", value)`, never an f-string) so a disabled log level costs nothing to format.
- Event-listener callbacks registered with Home Assistant must be decorated `@callback`. A missing decorator only fails on a real event loop.
- A broad `except Exception` needs an inline comment explaining why it's broad, and must log at least once. A silently swallowed error is never acceptable.

## Reporting Issues

Please use the [issue templates](https://github.com/hiall-fyi/yale_smart_alarm_ce/issues/new/choose) and include:

- Your Yale Smart Alarm CE and Home Assistant versions.
- The region you picked during setup, and whether the alarm was armed or disarmed when it happened.
- A diagnostics download. It's redacted automatically, so it's safe to attach.
- A debug log if the report involves unexpected behaviour, not just a screenshot.
- Steps to reproduce.

To report a security problem privately, see [SECURITY.md](SECURITY.md).
