import board
import busio
import adafruit_pca9685
import time

i2c = busio.I2C(board.SCL, board.SDA)
hat = adafruit_pca9685.PCA9685(i2c)

hat.frequency = 1500

motor_channels = [hat.channels[10], hat.channels[11]]

for channel in motor_channels:
    channel.duty_cycle = 0xFFFF  # Turn on motor
    time.sleep(2)
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
