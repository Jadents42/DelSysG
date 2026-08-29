#!/usr/bin/env python3
"""
Standalone diagnostic for divider_2's motor channels (PCA9685 channels 10 and 11).
Bypasses hardware_teleop.py and systemG_arch.py entirely - drives each channel
directly for a few seconds so you can watch/listen to the divider and isolate
whether one, both, or neither channel actually moves it.

Run this at the bench with eyes/ears on divider 2. Ctrl+C stops immediately and
always leaves the motor off.
"""
import time
import board
import busio
import adafruit_pca9685

CHANNELS = (10, 11)  # divider_2's motor channels, per systemG_arch.py's divider_motor_channels[1]
DUTY = 65535         # full power
DRIVE_TIME = 1.5     # seconds per test
PAUSE_TIME = 1.5     # seconds between tests, to visually separate the two


def brake(pwm_hat):
    pwm_hat.channels[CHANNELS[0]].duty_cycle = 0
    pwm_hat.channels[CHANNELS[1]].duty_cycle = 0


def main():
    print("Connecting to PWM hat (I2C address 0x41)...")
    i2c = busio.I2C(board.SCL, board.SDA)
    pwm_hat = adafruit_pca9685.PCA9685(i2c_bus=i2c, address=0x41)
    pwm_hat.frequency = 1500
    brake(pwm_hat)

    try:
        input("\nPress Enter to drive channel 10 only (this is the 'RIGHT'/increase-position channel)...")
        pwm_hat.channels[CHANNELS[0]].duty_cycle = DUTY
        pwm_hat.channels[CHANNELS[1]].duty_cycle = 0
        time.sleep(DRIVE_TIME)
        brake(pwm_hat)
        print("Stopped channel 10. Did divider 2 move?")
        time.sleep(PAUSE_TIME)

        input("\nPress Enter to drive channel 11 only (this is the 'LEFT'/decrease-position channel)...")
        pwm_hat.channels[CHANNELS[0]].duty_cycle = 0
        pwm_hat.channels[CHANNELS[1]].duty_cycle = DUTY
        time.sleep(DRIVE_TIME)
        brake(pwm_hat)
        print("Stopped channel 11. Did divider 2 move?")

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        brake(pwm_hat)
        print("Motor stopped, both channels zeroed.")


if __name__ == '__main__':
    main()
