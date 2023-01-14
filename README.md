# Home Assistant Custom Component for Stromnetz Graz

Home Assistant Custom Component for Stromnetz Graz integration.

You must have a working login to the [Stromnetz Graz Web Portal](https://webportal.stromnetz-graz.at/) and be able to see your meter readings there. Please refer to Stromnetz Graz how to set up access if you don't have it.

Please have `IME` mode (15 minute statistic interval) enabled (see [their FAQ](https://www.stromnetz-graz.at/sgg/stromzaehler/intelligenter-stromzaehler/faqs)), otherwise the statistics will not show properly in Home Assistant (see also **Limitations** below!)

After adding this integration, you are able to see the energy meter readings in the energy dashboard by adding the `stromnetzgraz:energy_consumption:1234` sensor to it (where 1234 is the meter id). You can add multiple sensors if you have multiple (for example for a hot water boiler).

**Do NOT add `sensor.meter_consumption_1234` or `sensor.meter_reading_1234` to the energy dashboard - it will not work!**

## Limitations

If you don't have `IME` mode enabled, the smart meter will only transmit daily summary data. So only the weekly/monthly report will look okay. If you choose to enable `IME` afterwards, please delete and re-add the integration.

Stromnetz Graz only provides the data for the previous day, there is no live data available. Because of that, the `sensor.meter_...` values are useless for long-time statistics (HA expects sensors to provide live data), but you might find the latest reading value useful elsewhere. The actual statistics are refreshed every six hours in the separate `stromnetzgraz:energy_consumption:...` sensors.

Because of that limitation, related values on the energy dashboard (CO₂ and price/money) might display strange and wrong values - they all expect live data to function properly.

## Installation (HACS)

When using HACS, just add this repository as a [custom repostiory](https://hacs.xyz/docs/navigation/settings#custom-repositories) of category `Integration` with the url `https://github.com/dreautall/ha-stromnetzgraz`.

## Installation (manual)

Place the folder `stromnetzgraz` and all it's files in the folder `custom_components` in the config folder of HA (where configuration.yaml is).

# Release notes

See [Github Releases](https://github.com/dreautall/ha-stromnetzgraz/releases/).

# Version

Can be used with Home Assistant >= `2022.2`
