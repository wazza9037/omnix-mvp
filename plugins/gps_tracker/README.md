# GPS Tracker Plugin

Real-time GPS position tracking with path recording and geofencing.

## Features

- NMEA-compatible GPS receiver support via serial
- Real-time position, speed, heading, and altitude
- Path recording with distance calculation
- Geofence zones with proximity alerts
- Map view integration
- Simulated figure-8 track for testing

## Configuration

| Field      | Description              | Default       |
|-----------|--------------------------|---------------|
| mode      | simulate / serial        | simulate      |
| port      | Serial port              | /dev/ttyUSB0  |
| baud      | Baud rate                | 9600          |
| start_lat | Starting latitude        | 37.7749       |
| start_lon | Starting longitude       | -122.4194     |

## Commands

- `start_recording` — Start recording GPS path
- `stop_recording` — Stop recording
- `clear_path` — Clear recorded path data
- `add_geofence` — Add a circular geofence zone
- `remove_geofence` — Remove a geofence by name
- `get_path` — Get recorded coordinates (last N points)

## Telemetry

Provides latitude, longitude, altitude, speed (m/s and km/h), heading, satellite count, fix quality, and geofence alert status.
