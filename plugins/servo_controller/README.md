# Servo Controller Plugin

Controls servo motors via PWM signals on Arduino, Raspberry Pi, or PCA9685 I2C driver.

## Features

- Multi-channel servo control (up to 16 servos)
- Angle control with min/max limits
- Sweep mode with configurable speed
- Coordinated pose commands for robot arm applications
- Simulated mode for testing without hardware

## Configuration

| Field        | Description                  | Default     |
|-------------|-------------------------------|-------------|
| servo_count | Number of servos              | 4           |
| mode        | simulate / arduino / pi_gpio / pca9685 | simulate |
| port        | Serial port (Arduino only)    | /dev/ttyACM0|
| min_pulse   | Min pulse width (µs)          | 500         |
| max_pulse   | Max pulse width (µs)          | 2500        |

## Commands

- `set_angle` — Set a servo to a specific angle (0-180)
- `sweep` — Sweep back and forth between min/max
- `stop_sweep` — Stop sweeping
- `home` — Return all servos to 90 degrees
- `set_speed` — Set movement speed in degrees/second
- `detach` — Disable PWM output on a channel
- `servo_pose` — Set multiple servos at once (custom command)
