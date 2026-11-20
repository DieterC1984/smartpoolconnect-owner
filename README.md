## ❤️ Support

If you find SmartPoolConnect Owner useful and would like to support its development, you can do so through GitHub Sponsors or PayPal.

Support is completely optional. The integration and all its features remain free and open source.

[❤️ Sponsor on GitHub](https://github.com/sponsors/DieterC1984)  
[☕ Support via PayPal](https://www.paypal.com/paypalme/DieterCeuppens)


# SmartPoolConnect Owner

Unofficial Home Assistant integration for SmartPoolConnect owner portals.

SmartPoolConnect Owner allows Home Assistant users to monitor and control supported swimming pool equipment through the SmartPoolConnect cloud platform.
The integration was originally developed and tested with the EPS Nexus Full Control system and has since been expanded through community testing to additional SmartPoolConnect-compatible systems, including Nexus II and Norsup One V3.


## Supported platforms

- **Nexus Full Control** - Stable
- **Nexus II Control** - Beta
- **Norsup One V3** - Beta


> [!IMPORTANT]
> This project is not affiliated with, endorsed by, or supported by EPS or SmartPoolConnect.


## Features

The exact entities available in Home Assistant depend on the equipment and
capabilities detected for your pool.

SmartPoolConnect Owner supports different SmartPoolConnect controller
generations and does not assume that every pool exposes the same hardware,
API or configuration.


### Monitoring

Depending on the installation:

- Pool online status
- Water temperature
- Ambient temperature
- System temperature IMX
- System temperature MAIN
- pH value
- Cl (Rx) / ORP value
- pH dosing flow status
- Cl dosing flow status
- Heating status
- Filter pump status
- Pump speed
- Cover state
- Cover position
- PHNIX heat-pump telemetry
- Last Backwash
- API Version
- Controller and firmware diagnostics


### Water Treatment

Supported configurations can expose:

- pH target
- pH dosing time
- pH pause time
- pH dosing flow status
- Cl (Rx) target
- Cl (Rx) dosing time
- Cl (Rx) pause time
- Cl dosing flow status

For compatible V3 controllers, confirmed setpoint writes are supported through
the SmartPoolConnect dosing configuration API.

Some V3 controllers report dosing and pause times in milliseconds. These values
are normalized for display in Home Assistant where detected.

Write support for dosing and pause timings is only enabled where the API
contract has been confirmed.

Dosing flow status is read from the corresponding SmartPoolConnect dosing
information and is not inferred from the filter pump state.


### Cl Shock Treatment

Supported installations can expose Cl Shock Treatment controls and status.

Available functionality includes:

- Cl Shock Treatment Status
- Start Cl Shock Treatment
- Stop Cl Shock Treatment

Confirmed treatment states include:

- Idle
- Waiting for Filter Pump
- Active

When a Cl Shock Treatment is started while the filter pump is stopped,
SmartPoolConnect may keep the treatment waiting until the filter pump starts.

SmartPoolConnect Owner does not automatically start the filter pump.

After a Start or Stop command, the integration performs an additional status
refresh after approximately 5 seconds so the Cl Shock state is reflected in
Home Assistant more quickly.


### Filtration

Depending on the controller:

- Filter pump control
- Pump status
- Pump speed
- Pump speed configuration
- Up to 3 configurable filter schedules
- Schedule enable/disable
- Weekday selection per schedule
- Schedule start and stop times

Pump-speed mappings can differ between controller generations.

Only confirmed mappings are used. Unknown controller-specific values are not
guessed.


### Backwash

Supported installations can expose:

- Backwash scheduling
- Backwash start date and time
- Backwash interval
- Backwash duration
- Rinse duration
- Backwash pump speed
- Manual / one-click Backwash trigger
- Last Backwash

Last Backwash is derived from SmartPoolConnect historical data.

The historical API uses aggregated time buckets, so the integration focuses on
the confirmed backwash date rather than presenting an imprecise bucket time as
the exact physical start time.


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

Where this telemetry is available, SmartPoolConnect Owner can use it for cover
state, encoder-based position and control.

The integration deliberately does not reproduce the SmartPoolConnect
`cover-protect` sampling or baseline-learning workflow.


### Heating and Temperature Control

Depending on the installation:

- Heating status
- Temperature target
- Temperature interval
- Cooling period
- Water temperature offset
- Ambient temperature offset
- Ambient temperature
- System temperature IMX
- System temperature MAIN

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

System and ambient temperatures available through SmartPoolConnect historical
data can also be exposed in Home Assistant.

MAIN system temperature is normalized from the controller's raw representation
to degrees Celsius.


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
- Related Zero-E status and configuration


### Lighting

Depending on the controller:

- Lighting on/off control
- Scheduled lighting operation
- Schedule start time
- Schedule stop time
- Monday-Sunday schedule selection
- Disable lighting when external/deck cover is closed
- Disable lighting when internal/Covco cover is closed

On compatible V3 controllers, lighting configuration is represented by a
bitmask.

SmartPoolConnect Owner uses read-modify-write handling so changing the lighting
state does not overwrite unrelated lighting and cover settings.


### Controller Diagnostics

Depending on the controller and available SmartPoolConnect data:

- API Version
- GUI Version
- MAIN Version
- IO Version
- DECK Version
- Controller/system temperatures
- Additional controller diagnostics

API Version is exposed as diagnostic information, for example:

- `v2`
- `v3`

The reported API version is not used to hard-code which live endpoint a pool
must use. SmartPoolConnect Owner keeps its capability-driven approach and
supports the available SmartPoolConnect data sources independently.


### Language Support

SmartPoolConnect Owner currently includes translations for:

- English
- Dutch
- German

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

<img width="265" height="1164" alt="image" src="https://github.com/user-attachments/assets/c6338fed-0d72-4ee0-8246-b8abc42900ec" />
<img width="263" height="1209" alt="image" src="https://github.com/user-attachments/assets/dd85a6ba-74a5-4008-91f8-c642a5b0105a" />
<img width="268" height="1225" alt="image" src="https://github.com/user-attachments/assets/6c12cc95-fd31-4267-aadf-e7dd1f359dce" />
<img width="268" height="737" alt="image" src="https://github.com/user-attachments/assets/596476e2-3d9b-49b7-9d69-88f6edf3fcea" />



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
