## ❤️ Support

If you find SmartPoolConnect Owner useful and would like to support its development, you can do so through GitHub Sponsors or PayPal.

Support is completely optional. The integration and all its features remain free and open source.

[❤️ Sponsor on GitHub](https://github.com/sponsors/DieterC1984)  
[☕ Support via PayPal](https://www.paypal.com/paypalme/DieterCeuppens)


# SmartPoolConnect Owner

Unofficial Home Assistant integration for SmartPoolConnect owner portals.

SmartPoolConnect Owner allows Home Assistant users to monitor and control supported swimming pool equipment through the SmartPoolConnect cloud portal from EPS (Europe Pool Supplies).

The integration was originally developed for the **EPS Nexus Full Control** system and has since been expanded to support additional SmartPoolConnect controller generations and pool configurations.

## Supported platforms

- **Nexus Full Control** - Stable
- **Nexus II Control** - Beta
- **Norsup One V3** - Beta


SmartPoolConnect installations can expose different APIs, controller modules and capabilities. The integration therefore detects supported functionality dynamically instead of assuming that every pool has the same equipment.

> [!IMPORTANT]
> This project is not affiliated with, endorsed by, or supported by EPS or SmartPoolConnect.


## Features

The exact entities available in Home Assistant depend on the equipment and capabilities detected for your pool.


### Monitoring

Depending on the installation:

- Pool online status
- Water temperature
- Ambient temperature
- pH value
- Rx / ORP value
- Heating status
- Filter pump status
- Pump speed
- Cover state
- Cover position
- PHNIX heat-pump telemetry
- Additional controller diagnostics


### Water Treatment

Supported configurations can expose:

- pH target
- pH dosing time
- pH pause time
- Rx / ORP target
- Rx dosing time
- Rx pause time

For compatible V3 controllers, confirmed setpoint writes are supported through the SmartPoolConnect dosing configuration API.

Some V3 controllers report dosing and pause times in milliseconds. These values are normalized for display in Home Assistant where detected.

Write support for dosing/pause timings is only enabled where the API contract has been confirmed.


### Filtration

Depending on the controller:

- Filter pump control
- Pump status
- Pump speed configuration
- Up to 3 filter schedules
- Schedule enable/disable
- Weekday selection per schedule
- Schedule start and stop times

> [!NOTE]
> Pump-speed mappings can differ between controller generations. Additional V3 mappings are still being validated during the beta.


### Backwash

Supported installations can expose:

- Backwash scheduling
- Backwash start date
- Backwash start time
- Backwash interval
- Backwash duration
- Rinse duration
- Backwash pump speed
- Manual / one-click backwash trigger


### Cover Control

Depending on the installed cover configuration:

- Open cover
- Close cover
- Stop cover movement
- Cover state
- Cover position
- Cover movement state
- Automatic pump behaviour during cover movement
- Optional slow-speed behaviour during cover movement

Some SmartPoolConnect installations expose their internal cover through
`covco_data`. SmartPoolConnect itself refers to this as the
**internal / Covco cover**.

Where this telemetry is available, SmartPoolConnect Owner can use it for
cover state, position and control.


### Heating and Temperature Control

Depending on the installation:

- Heating status
- Temperature target
- Temperature interval
- Cooling period
- Water temperature offset
- Ambient temperature offset

Compatible PHNIX-equipped installations can additionally expose:

- PHNIX setpoint
- Inlet temperature
- Outlet temperature
- Ambient temperature
- Coil temperature
- Operating mode
- Sub-mode
- Error information
- Failure information


### Eco Valve

Supported installations can expose:

- Eco Valve control
- Eco Valve scheduling
- Eco Valve start time
- Eco Valve stop time


### Zero-E

On installations exposing Zero-E functionality:

- Enable threshold
- Disable threshold
- Target temperature
- Related Zero-E status/configuration


### Lighting

Depending on the controller:

- Lighting on/off control
- Scheduled lighting operation
- Schedule start time
- Schedule stop time
- Monday-Sunday schedule selection
- Disable lighting when external/deck cover is closed
- Disable lighting when internal/Covco cover is closed

On compatible V3 controllers, lighting configuration is represented by a bitmask. SmartPoolConnect Owner preserves unrelated lighting flags when changing the on/off state instead of overwriting the complete configuration.


## Multi-controller support

SmartPoolConnect does not expose exactly the same backend structure for every pool.

SmartPoolConnect Owner currently supports multiple live-data mechanisms, including:

- `/api/live-status/{pool_id}`
- `/api/v3-live/{pool_id}`

`v3-live` does **not** replace `live-status`.

Both are supported because different SmartPoolConnect controller generations and pool installations use different data sources.

The integration uses capability detection to determine which functionality is available.

For example:

- A pool without PHNIX should not receive PHNIX entities.
- A pool without Covco telemetry should not depend on Covco-specific code.
- A `live-status` pool does not need to support `v3-live`.
- A V3 pool can expose functionality not present on older controllers.

The goal is to support different SmartPoolConnect pool configurations without tailoring the integration to one specific installation.


## Installation

### Installation with HACS

1. Open HACS in Home Assistant.
2. Go to **Integrations**.
3. Search for **SmartPoolConnect Owner**.
4. Select **SmartPoolConnect Owner** and click **Download**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration**.
7. Search for **SmartPoolConnect Owner**.
8. Follow the setup instructions.


### Custom repository installation

If you want to install a beta, development or unreleased version:

1. Open HACS in Home Assistant.
2. Go to **Integrations**.
3. Open the menu and choose **Custom repositories**.
4. Add the SmartPoolConnect Owner GitHub repository URL.
5. Set the category to **Integration**.
6. Install **SmartPoolConnect Owner**.
7. Select the desired release when testing a beta version.
8. Restart Home Assistant.
9. Go to **Settings → Devices & services → Add integration**.
10. Search for **SmartPoolConnect Owner**.


### Manual installation

Copy:

`custom_components/smartpoolconnect_owner`

to:

`/config/custom_components/smartpoolconnect_owner`

Restart Home Assistant and add **SmartPoolConnect Owner** through:

**Settings → Devices & services → Add integration**


## Configuration

The integration is configured through the Home Assistant UI.

You need:

- SmartPoolConnect owner portal credentials
- The pool UUID used by the SmartPoolConnect owner portal

Entity creation is based on the capabilities detected for that pool.

This means two SmartPoolConnect installations can legitimately expose different sets of Home Assistant entities.


## Supported entities

SmartPoolConnect Owner uses standard Home Assistant entity platforms, including where supported:

- Sensors
- Binary sensors
- Switches
- Numbers
- Selects
- Time entities
- Date entities
- Buttons
- Cover entities

The exact entities available depend on your controller, installed equipment and SmartPoolConnect configuration.

<img width="447" height="1251" alt="SmartPoolConnect Owner entities in Home Assistant" src="https://github.com/user-attachments/assets/b0778da4-7e39-4074-80ab-c0673aaeacbe" />


## Beta testing

Support for additional SmartPoolConnect controller generations is actively being expanded.

Feedback is particularly welcome from users with:

- Nexus II Control
- Norsup One V3
- Covco covers
- PHNIX heat pumps
- Different filtration/pump configurations
- Different dosing configurations
- Different lighting and cover combinations

When reporting controller differences, please include:

- Controller/platform type
- Integration version
- Expected behaviour
- Home Assistant behaviour
- Relevant entity states
- Sanitized API information if available

Do **not** publish your pool UUID, credentials, authentication tokens, session cookies or other personal information.


## Notes and limitations

SmartPoolConnect is a cloud-based service. This integration therefore depends on the availability and behaviour of the SmartPoolConnect portal and its backend APIs.

SmartPoolConnect is not known to expose one single public API contract covering every supported controller generation. Backend behaviour can differ between pool configurations.

For this reason, new functionality is introduced conservatively and only after the relevant API behaviour has been observed and validated.

Beta functionality may change as additional controller configurations are tested.


## Privacy and security

When reporting an issue, always remove:

- SmartPoolConnect username/email
- Password
- Pool UUID/GUID
- Authentication tokens
- Cookies
- Session information
- Personal information

Full raw SmartPoolConnect responses may contain identifying information. Sanitize them before posting publicly.


## Disclaimer

Use this integration at your own risk.

Swimming pool equipment can include pumps, dosing systems, heating equipment, valves, covers and electrical equipment. Incorrect operation or configuration can cause equipment damage or create unsafe conditions.

Always verify safety-critical configuration changes in the official SmartPoolConnect interface and, where appropriate, directly on the physical pool installation.

SmartPoolConnect Owner deliberately avoids interacting with controller protection/learning mechanisms where their behaviour has not been sufficiently validated.
