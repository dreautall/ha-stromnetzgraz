# Stromnetz Graz for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/mainman94/ha-stromnetzgraz/actions/workflows/validate_hacs.yaml/badge.svg)](https://github.com/mainman94/ha-stromnetzgraz/actions/workflows/validate_hacs.yaml)
[![hassfest](https://github.com/mainman94/ha-stromnetzgraz/actions/workflows/validate_hassfest.yaml/badge.svg)](https://github.com/mainman94/ha-stromnetzgraz/actions/workflows/validate_hassfest.yaml)
[![License: MIT](https://img.shields.io/github/license/mainman94/ha-stromnetzgraz)](LICENSE)

A Home Assistant custom integration that imports your smart-meter consumption
from the [Stromnetz Graz web portal](https://webportal.stromnetz-graz.at/) into
the energy dashboard.

This is a maintained fork of
[dreautall/ha-stromnetzgraz](https://github.com/dreautall/ha-stromnetzgraz).
It keeps working with current Home Assistant releases. These are the changes
compared to upstream:

- **Missing meter readings no longer break the integration.** When Stromnetz
  Graz sends no meter readings for the fetched period (for example after a day
  with no data), the update used to crash with `KeyError: 'MR'` and every
  sensor went `unavailable`.
- **Works with Home Assistant 2026.11 and later.** The statistics import sets
  `mean_type` and `unit_class`, so HA no longer rejects it with the deprecation
  warning.
- **No blocking calls in the event loop.** Certificates are loaded off the
  event loop.
- **The same account can't be added twice.** A duplicate entry used to cause
  `does not generate unique IDs` errors.

## Requirements

- Home Assistant **2025.11** or newer.
- A working login for the
  [Stromnetz Graz web portal](https://webportal.stromnetz-graz.at/), where you
  can already see your meter readings. Ask Stromnetz Graz how to set up access
  if you don't have it yet.
- **IME mode** (15-minute values) enabled for your meter. See the
  [Stromnetz Graz FAQ](https://www.stromnetz-graz.at/sgg/stromzaehler/intelligenter-stromzaehler/faqs).
  Without it the meter only reports daily totals, and only the weekly and
  monthly views of the energy dashboard look right.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/mainman94/ha-stromnetzgraz` with type
   **Integration**.
3. Install **Stromnetz Graz Integration** and restart Home Assistant.

If you are switching from the upstream repository: remove it in HACS (not the
integration under *Devices & services*), add this one and install it. The
domain is the same, so your config entry and imported statistics stay.

### Manual

Copy `custom_components/stromnetzgraz/` into the `custom_components/` folder of
your Home Assistant config directory (where `configuration.yaml` lives), then
restart Home Assistant.

## Setup

Go to **Settings → Devices & services → Add integration → Stromnetz Graz** and
enter your web portal e-mail and password.

Then add the statistic `stromnetzgraz:energy_consumption:<meter id>` to the
**energy dashboard** under *Electricity grid → Grid consumption*. If you have
several meters (for example a separate one for a hot-water boiler), add each of
them.

> **Don't** add `sensor.*_meter_consumption_*` or `sensor.*_meter_reading_*`
> to the energy dashboard. Those show the last reported value, not a running
> total, so the dashboard numbers would be wrong.

## Limitations

- **No live data.** Stromnetz Graz publishes the previous day's values, so
  today's consumption always shows up the next day. The statistics are
  refreshed every six hours, and the last 30 days are re-imported each time to
  pick up corrections.
- **CO₂ and cost on the energy dashboard** expect live data and can show odd
  values for this source.
- **Enabling IME later:** delete the integration and add it again, so the
  history is imported at 15-minute resolution.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Sensors `unavailable`, `KeyError: 'MR'` in the log | You are on upstream ≤ 0.1.14. Update to this fork. |
| A day is missing in the energy dashboard | Check the web portal. If the day is missing there too, Stromnetz Graz has no data for it yet. They usually deliver it later, and the next import fills the gap. |
| `sensor.*_meter_reading_*` is `unknown` | Stromnetz Graz sent no meter reading for the last 30 days. Consumption is still imported. |
| `Platform stromnetzgraz does not generate unique IDs` | The same account was added twice. Delete one of the two entries. |

When you open an issue, include the log lines that mention `stromnetzgraz`,
with your e-mail address and meter IDs redacted. Use the
[bug report form](https://github.com/mainman94/ha-stromnetzgraz/issues/new/choose).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to test a change and how to cut
a release. Report security issues privately as described in
[SECURITY.md](SECURITY.md).

## Release notes

See [GitHub Releases](https://github.com/mainman94/ha-stromnetzgraz/releases/).

## Credits

Originally written by [@dreautall](https://github.com/dreautall). The API
client is [stromnetzgraz](https://github.com/dreautall/stromnetzgraz) on PyPI.
Licensed under [MIT](LICENSE).
