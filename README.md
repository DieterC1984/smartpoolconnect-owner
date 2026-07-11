# SmartPoolConnect Owner

Unofficial Home Assistant integration for SmartPoolConnect owner portals.

This custom integration lets Home Assistant read and control supported SmartPoolConnect owner-portal functions from the cloud portal.

> This project is not affiliated with, endorsed by, or supported by SmartPoolConnect.

## Features

- Pool online/status information
- pH current value
- pH target and dosing configuration
- Rx / ORP current value
- Rx / ORP target and dosing configuration
- Water temperature and other available pool sensors
- Pool cover / deck control
- Lighting configuration
- Filter pump configuration
- Filter schedules with weekday selection
- Backwash configuration
- Start Backwash button
- Eco Valve configuration

## Installation with HACS

1. Open HACS in Home Assistant.
2. Go to **Integrations**.
3. Open the menu and choose **Custom repositories**.
4. Add your GitHub repository URL.
5. Set the category to **Integration**.
6. Install **SmartPoolConnect Owner**.
7. Restart Home Assistant.
8. Go to **Settings → Devices & services → Add integration**.
9. Search for **SmartPoolConnect Owner**.

## Manual installation

Copy this folder:

```text
custom_components/smartpoolconnect_owner
```

into your Home Assistant configuration directory:

```text
/config/custom_components/smartpoolconnect_owner
```

Restart Home Assistant and add the integration from the UI.

## Configuration

The integration can be configured from the Home Assistant UI.

You need:

- SmartPoolConnect owner portal credentials, and
- the pool UUID used by the SmartPoolConnect owner portal.

Do not publish credentials, session cookies, pool UUIDs, or raw portal responses in GitHub issues.

## Supported entities

The exact available entities depend on the capabilities of your SmartPoolConnect installation.

Typical entities include:

- pH sensor
- Rx / ORP sensor
- pH target
- Rx / ORP target
- pH dosing time
- Rx dosing time
- Filter pump speed
- Filter schedules
- Lighting schedule
- Cover / deck controls
- Backwash settings
- Start Backwash button
- Eco Valve regulation

## Notes and limitations

SmartPoolConnect uses a cloud portal. This integration depends on the availability and behavior of that portal.

Some values may be exposed by the portal only as writeable settings and may not always be returned clearly through the read endpoints. In those cases the integration uses safe defaults to keep entities usable.

## Privacy and security

This repository should not contain:

- usernames
- passwords
- session cookies
- pool UUIDs
- pool names
- raw API responses
- Home Assistant logs containing personal data

If you open an issue, remove sensitive information first.

## Disclaimer

Use this integration at your own risk. Pool equipment can be safety-sensitive. Always verify critical changes in the official SmartPoolConnect portal or on the physical installation.
