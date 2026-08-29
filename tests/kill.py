import board
import busio
import adafruit_pca9685
import time

i2c = busio.I2C(board.SCL, board.SDA)
hat = adafruit_pca9685.PCA9685(i2c)

hat.frequency = 1500

for i in range(16):
    channel = hat.channels[i]
    channel.duty_cycle = 0x0000  # Turn off motor
    time.sleep(0.1)