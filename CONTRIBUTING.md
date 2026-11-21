# Contributing

Thanks for helping out. This is a maintained fork of
[dreautall/ha-stromnetzgraz](https://github.com/dreautall/ha-stromnetzgraz): a
Home Assistant custom integration that imports Stromnetz Graz smart-meter data.

## Layout

| Path                                              | What it is                                            |
| ------------------------------------------------- | ----------------------------------------------------- |
| `custom_components/stromnetzgraz/__init__.py`     | Config entry setup, API client creation               |
| `custom_components/stromnetzgraz/config_flow.py`  | The login form                                        |
| `custom_components/stromnetzgraz/sensor.py`       | Sensors and the external long-term statistics import  |
| `custom_components/stromnetzgraz/sngraz/`         | The Stromnetz Graz API client (from the `stromnetzgraz` package) |
| `custom_components/stromnetzgraz/manifest.json`   | Version, requirements (pandas)                        |
| `custom_components/stromnetzgraz/strings.json`    | UI text, mirrored in `translations/{de,en}.json`      |
| `hacs.json`                                       | HACS metadata, including the minimum HA version       |
| `.github/workflows/`                              | The `hacs` and `hassfest` checks                      |

## Testing a change

`tests/` covers the cost calculation (`cost.py`), the one part that runs
without Home Assistant:

```shell
uvx --with pandas pytest tests/
```

Everything else needs a real instance. Copy `custom_components/stromnetzgraz/` into the
`custom_components/` folder of a Home Assistant instance with a Stromnetz Graz
login, restart Home Assistant and check:

- the log has no errors or warnings from `custom_components.stromnetzgraz`
- the `sensor.*_meter_*` entities have values
- the `stromnetzgraz:energy_consumption:<meter>` statistics keep growing in
  the energy dashboard

Data arrives once a day, so the statistics only change after the next import
(every six hours).

## Pull requests

- One topic per PR, branch off `master`.
- Bump `version` in `manifest.json`.
- A new key in `strings.json` goes into both `translations/de.json` and
  `translations/en.json`; hassfest fails otherwise.
- Say which Home Assistant version you tested on.
- Commit messages: conventional style, imperative mood
  (`fix: survive missing meter readings`).

Two checks must pass before a PR can merge: `hacs` (HACS validation) and
`hassfest` (Home Assistant's manifest and translation checks). `master` is
protected; every change, including upstream syncs, goes through a PR.

## Syncing upstream

```shell
git fetch upstream
git switch -c chore/sync-upstream master
git rebase upstream/master   # or cherry-pick the commits you want
git push -u origin chore/sync-upstream
gh pr create --repo mainman94/ha-stromnetzgraz --fill
```

GitHub's "Sync fork" button pushes to `master` directly and is blocked by the
branch ruleset.

## Releases

HACS installs from GitHub releases. After the version bump is merged:

```shell
gh release create v0.1.15 --repo mainman94/ha-stromnetzgraz --generate-notes
```

The tag must match `version` in `manifest.json`, prefixed with `v`.
