# Security Policy

## Supported versions

Only the latest [release](https://github.com/mainman94/ha-stromnetzgraz/releases)
receives fixes. HACS offers it as an update; older versions stay installable
but are not patched.

## Reporting a vulnerability

Report privately via GitHub's
[security advisories](https://github.com/mainman94/ha-stromnetzgraz/security/advisories/new).
Please do not open a public issue for anything exploitable.

Expect an acknowledgement within a few days. Include the integration version,
the Home Assistant version and steps to reproduce.

Report here only what this integration adds. Vulnerabilities in the API client
library belong to [dreautall/stromnetzgraz](https://github.com/dreautall/stromnetzgraz),
ones in Home Assistant itself to
[home-assistant/core](https://github.com/home-assistant/core/security).

## How credentials are handled

- Your Stromnetz Graz web portal e-mail and password are stored in the Home
  Assistant config entry (`.storage/core.config_entries`), like any integration
  with a password login. Anyone with access to your Home Assistant config
  directory or its backups can read them.
- The integration talks only to `https://webportal.stromnetz-graz.at/api/`,
  over TLS with certificate verification on.
- Redact your e-mail address, password and meter IDs before posting logs in an
  issue.
