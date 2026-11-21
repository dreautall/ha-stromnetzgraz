# AGENTS

Home Assistant custom integration (HACS) for Stromnetz Graz smart-meter data.
This is a fork: `origin` is mainman94, `upstream` is dreautall. Keep changes
small and upstream-friendly.

## Layout

- `custom_components/stromnetzgraz/`: the integration (`__init__.py`,
  `config_flow.py`, `sensor.py`, `cost.py`, `stats.py`, `const.py`).
- `sngraz/`: the API client, taken over from the unmaintained
  [stromnetzgraz](https://github.com/dreautall/stromnetzgraz) package (MIT, see
  its `LICENSE`). Fix client bugs there instead of working around them.
- `manifest.json`: version, HA dependencies, and Python requirements (`pandas`).
- `strings.json` + `translations/{de,en}.json`: UI text.
- `brand/icon.png` (+ `@2x`): the icon HACS and Home Assistant show. A generic
  lightning bolt on purpose, not the Stromnetz Graz logo (their trademark).

## Checks

`tests/` only covers `cost.py`, `stats.py` and pure helpers of the API client
(`uvx --with pandas --with aiohttp --with pyjwt pytest tests/`); everything else needs a Home Assistant
instance. CI runs the `pytest`, `hacs` and `hassfest` jobs on every PR; `hacs` and `hassfest` are required checks (ruleset managed in `mainman94/homelab`,
`terraform/github`). Renaming a job silently breaks the ruleset — change both together.

## Conventions

- Bump `version` in `manifest.json` for every release.
- A new key in `strings.json` must be added to both `translations/de.json` and
  `translations/en.json`. hassfest fails on a mismatch.
- Data arrives once a day (no live values). Long-term statistics go into the
  `stromnetzgraz:energy_consumption_<meter>` external statistics, not into the
  `sensor.meter_*` entities. See README "Limitations".
- The `sngraz` client raises `SNGrazError` (with the response body) on HTTP errors
  and `InvalidLogin` on a rejected login. It still returns `None` for missing data
  (e.g. no readings), so check return values too.
- The API reads every date as Vienna wall-clock time and ignores UTC offsets; format
  dates with `sngraz.api_time()`.
- Network calls belong in `__init__.async_setup_entry` (raise `ConfigEntryNotReady`
  / `ConfigEntryAuthFailed`); `sensor.py` setup only builds entities.
