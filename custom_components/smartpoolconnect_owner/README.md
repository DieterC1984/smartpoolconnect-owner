# SmartPoolConnect Owner Portal - Home Assistant custom integration

Experimental owner-login based integration for the new SmartPoolConnect portal.

## New portal endpoints mapped

Read:

```text
GET /api/live-status/<pool_uuid>
GET /api/pool-status/<pool_uuid>
```

Write:

```text
PATCH /pool/<pool_uuid>/lighting.data
POST /api/cmd/<pool_uuid>/cover_open
POST /api/cmd/<pool_uuid>/cover_close
POST /api/cmd/<pool_uuid>/cover_stop
```

## Authentication
Uses SmartPoolConnect web-portal session/OAuth flow, not a shared `spc_` API key.
Each user must use their own owner credentials.

## Safety
The cover entity is included but disabled by default. Enable only if you can independently verify the pool area is clear before every command.
