# SmartPoolConnect Owner

Unofficial Home Assistant integration for SmartPoolConnect owner portals.

This custom integration allows Home Assistant users to monitor and control supported SmartPoolConnect swimming pool functions through the SmartPoolConnect cloud portal from EPS (Europe Pool Supplies), and is designed for swimming pools equipped with the EPS Nexus Full Control system.

> This project is not affiliated with, endorsed by, or supported by EPS.


## Features

### Monitoring
- Pool online status
- Water temperature
- pH value
- Rx value
- Heating status
- Pump status and current speed
- Cover status

### Water Treatment
- pH dosing target configuration
- pH dosing time configuration
- pH dosing pause time configuration
- Rx dosing target configuration
- Rx dosing time configuration
- Rx dosing pause time configuration

### Filtration
- Filter pump control
- Filter pump speed configuration
- Up to 3 configurable filter schedules
- Weekday selection per schedule
- Schedule start and stop times

### Backwash
- Backwash scheduling
- Backwash start date and time
- Backwash interval configuration
- Backwash duration configuration
- Backwash rinse duration configuration
- Backwash pump speed configuration
- One-click Backwash trigger

### Cover Control
- Open and close pool cover
- Cover protection settings
- Automatic pump shutdown during pool cover movement
- Optional slow-speed mode for cover opening and closing


### Eco Valve
- Eco Valve control
- Eco Valve scheduling
- Eco Valve Start and stop time configuration

### Lighting
- Lighting control
- Scheduled lighting operation
- Weekday-based lighting schedules
- Cover-aware lighting behavior

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

<img width="447" height="1251" alt="image" src="https://github.com/user-attachments/assets/b0778da4-7e39-4074-80ab-c0673aaeacbe" />

## Notes and limitations

SmartPoolConnect uses a cloud portal. This integration depends on the availability and behavior of that portal.

## Privacy and security
If you open an issue, remove sensitive information first.

## Disclaimer
Use this integration at your own risk. Pool equipment can be safety-sensitive. Always verify critical changes in the official SmartPoolConnect portal or on the physical installation.
