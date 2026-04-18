# Weather Station Plugin

Environmental monitoring with temperature, humidity, and barometric pressure.

## Features

- BME280/BMP280 sensor support via I2C
- Derived readings: altitude, dew point, heat index
- Simple pressure-trend weather forecasting
- Configurable read interval
- Rolling history (500 readings)
- Weather dashboard widget

## Sensors

| Channel      | Type        | Unit  | Range          |
|-------------|-------------|-------|----------------|
| temperature | temperature | °C    | -40 to 85      |
| humidity    | humidity    | %     | 0 to 100       |
| pressure    | pressure    | hPa   | 300 to 1100    |
| altitude    | barometer   | m     | derived        |
| dew_point   | temperature | °C    | derived        |
| heat_index  | temperature | °C    | derived        |

## Commands

- `read_sensors` — Force an immediate sensor read
- `set_interval` — Change the read interval (0.5-60 seconds)
- `reset_history` — Clear sensor reading history
- `get_forecast` — Simple pressure-trend weather forecast
