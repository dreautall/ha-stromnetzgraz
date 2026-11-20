# AGENTS

Home Assistant custom integration (HACS) for Stromnetz Graz smart-meter data.
This is a fork: `origin` is mainman94, `upstream` is dreautall. Keep changes
small and upstream-friendly.

## Layout

- `custom_components/stromnetzgraz/`: the integration (`__init__.py`,
  `config_flow.py`, `sensor.py`, `const.py`).
- `manifest.json`: version, HA dependencies, and pinned Python requirements
  (`stromnetzgraz` client library, `pandas`).
- `strings.json` + `translations/{de,en}.json`: UI text.

## Checks

There is no local test suite. CI runs the `hacs` and `hassfest` jobs on every PR;
both are required checks (ruleset managed in `mainman94/homelab`,
`terraform/github`). Renaming a job silently breaks the ruleset — change both together.

## Conventions

- Bump `version` in `manifest.json` for every release.
- A new key in `strings.json` must be added to both `translations/de.json` and
  `translations/en.json`. hassfest fails on a mismatch.
- Data arrives once a day (no live values). Long-term statistics go into the
  `stromnetzgraz:energy_consumption:<meter>` external statistics, not into the
  `sensor.meter_*` entities. See README "Limitations".
