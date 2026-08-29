import board
import busio
import adafruit_pca9685
import pi_servo_hat
import time

i2c = busio.I2C(board.SCL, board.SDA)
hat = adafruit_pca9685.PCA9685(i2c, address=0x41)
servo_hat = pi_servo_hat.PiServoHat(min_pt=0.5, max_pt=2.5, address=0x40)
servo_hat.restart()

time.sleep(2)
servo_hat.move_servo_position(1, 0, 180)
time.sleep(2)

servo_hat.sleep()


hat.frequency = 1500

motor_channels = [hat.channels[1], hat.channels[3]]

for channel in motor_channels:
    channel.duty_cycle = 0xFFFF  # Turn on motor

time.sleep(2)

for channel in motor_channels:
    channel.duty_cycle = 0x0000  # Turn off motor

# servo_channels = [hat.channels[12], hat.channels[13], hat.channels[14], hat.channels[15]]

# for channel in servo_channels:
#     channel.duty_cycle = 0x2000  # Move to position 1
#     time.sleep(1)
#     channel.duty_cycle = 0x4000  # Move to position 2
#     time.sleep(1)
#     channel.duty_cycle = 0x6000  # Move to position 3
#     time.sleep(1)
#     channel.duty_cycle = 0x0000  # Turn off servo
