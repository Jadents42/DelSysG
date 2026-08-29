import time
import sys
import math
import board
import busio
import qwiic_scmd
import pi_servo_hat
import qwiic_dual_encoder_reader
import adafruit_pca9685
from adafruit_servokit import ServoKit
from adafruit_motorkit import MotorKit
import threading

class SystemG():
    def __init__(self):
        self.partitions_idx = [1, 2, 3]
        self.max_div_pos = 900 # mm CHECK
        self.max_rail_pos = 300 # mm CHECK
        self.RAIL_LEFT_ENDSTOP = 0 # mm
        self.RAIL_RIGHT_ENDSTOP = self.max_rail_pos # mm
        self.max_door_pos = 400 # mm CHECK
        self.div_tol = 2 # mm
        self.rail_tol = 2 # mm
        self.door_tol = 4 # mm

        # Initialize Constructor
        I2C = busio.I2C(board.SCL, board.SDA)

        # PWM Pi Hat channels
        self.pwm_hat = adafruit_pca9685.PCA9685(i2c_bus=I2C)
        self.pwm_hat.frequency = 60
        # Motor channels for [rail 0, rail 1, rail 2, rail 3]
        self.rail_motor_channels = [(0, 1), (2, 3), (4, 5), (6, 7)]
        # Motor channels for [divider 1, divider 2]
        self.divider_motor_channels = [(8, 9), (10, 11)]


        self.servo_hat = ServoKit(channels=16, i2c=I2C)
        # Servo channels for [rail 0, rail 1, rail 2, rail 3]
        self.servo_channels = [12, 13, 14, 15]
        for i in self.servo_channels:
            self.servo_hat.servo[i].actuation_range = 270
            self.servo_hat.servo[i].set_pulse_width_range(500, 2500)
        self.engaged = [False, False, False, False]

        # DC + Stepper Motor Pi Hat channels
        # self.step_hat = MotorKit(i2c=i2c, address=60)
        # # Motor channels for [left, right]
        # self.door_motor_channels = [self.step_hat.motor1, self.step_hat.motor2]

        # Actual position of dividers [divider 1, divider 2]
        self.div_pos = [20, 40]
        # Actual position of rails [rail 0, rail 1, rail 2, rail 3]
        self.rail_pos = [0, 0, 0, 0]
        # Actual position of doors [left, right]
        self.door_pos = [0, 0]

        self.enc_lock = threading.Lock()
        self.enc_ser_thread = threading.Thread(target=self._encoder_serial_thread, daemon=True)
        self.enc_hat_thread = threading.Thread(target=self._encoder_hat_thread, daemon=True)
        self.enc_ser_thread.start()
        #self.enc_hat_thread.start()


    def move_divider(self, div_idx: int, set_pos: float):
        '''
        Takes in the divider index and the set position in mm
        Runs until the divider reaches the set position within tolerance
        (Thread safe with encoder updates)
        '''
        if div_idx not in self.partitions_idx[:-1]:
            print("Invalid partition referenced")
            print(f"{div_idx} is not in {self.partitions_idx[:-1]}")
            return

        if div_idx == 1:
            if set_pos > self.div_pos[1] - self.div_tol:
                print("Divider 1 cannot move beyond Divider 2")
                return
        
        if div_idx == 2:
            if set_pos < self.div_pos[0] + self.div_tol + 20:
                print("Divider 2 cannot move beyond Divider 1")
                return
        
        div_idx -= 1
        
        assert div_idx >= 0
        assert div_idx < len(self.divider_motor_channels)
        assert 0 <= set_pos <= self.max_div_pos

        ch = self.divider_motor_channels[div_idx]
        in_range = False

        while not in_range:
            if self.div_pos[div_idx] < set_pos:
                self.drive_pwm_motor(ch, 1.0)
            else:
                self.drive_pwm_motor(ch, -1.0)

            with self.enc_lock:
                if (set_pos - self.div_tol < self.div_pos[div_idx] < set_pos + self.div_tol):
                    in_range = True
        
        self.drive_pwm_motor(ch, 0.0)

    def move_pushers(self, part_idx: int, set_pos: float):
        '''
        Takes in the partiton index and the set position in mm
        Runs until the rails reach the set position within tolerance
        (Thread safe with encoder updates)
        '''
        if part_idx not in self.partitions_idx:
            print("Invalid partition referenced")
            print(f"{part_idx} is not in {self.partitions_idx}")
            return
        
        assert part_idx >= 0
        assert part_idx < len(self.rail_motor_channels)
        assert 0 <= set_pos <= self.max_rail_pos

        r_ch = self.rail_motor_channels[part_idx]
        l_ch = self.rail_motor_channels[part_idx - 1]
        r_in_range = False
        l_in_range = False

        while not (l_in_range and r_in_range):
            if r_in_range:
                self.drive_pwm_motor(r_ch, 0.0)
            elif self.rail_pos[part_idx] < set_pos:
                self.drive_pwm_motor(r_ch, 1.0)
            else:
                self.drive_pwm_motor(r_ch, -1.0)

            if l_in_range:
                self.drive_pwm_motor(l_ch, 0.0)
            elif self.rail_pos[part_idx - 1] < set_pos:
                self.drive_pwm_motor(l_ch, 1.0)
            else:
                self.drive_pwm_motor(l_ch, -1.0)

            with self.enc_lock:
                if (set_pos - self.rail_tol < self.rail_pos[part_idx] < set_pos + self.rail_tol):
                    r_in_range = True
                if (set_pos - self.rail_tol < self.rail_pos[part_idx - 1] < set_pos + self.rail_tol):
                    l_in_range = True
        
        self.drive_pwm_motor(r_ch, 0.0)
        self.drive_pwm_motor(l_ch, 0.0)

    def engage_pushers(self, part_idx: int, engage: bool = True):
        '''
        Takes in the partition index and whether to engage (True) or disengage (False)
        Turns the servos to the appropriate angle
        '''
        if part_idx not in self.partitions_idx:
            print("Invalid partition referenced")
            print(f"{part_idx} is not in {self.partitions_idx}")
            return
        
        assert part_idx - 1 >= 0
        assert part_idx < len(self.servo_channels)
        left = self.servo_channels[part_idx - 1]
        right = self.servo_channels[part_idx]

        angle = 180 if engage else 90

        # Left servo
        self.servo_hat.servo[left].angle = angle
        # Right servo 
        self.servo_hat.servo[right].angle = angle - 90

        self.engaged[part_idx - 1] = engage
        self.engaged[part_idx] = engage
    
    def drive_pwm_motor(self, motor_channels: list[int, int], speed=1.0):
        '''
        Drives a motor connected to the specified PWM Hat channels at the given speed.
        For motors driven by the PWM Pi Hat only
        '''
        assert len(motor_channels) == 2
        assert 0 <= motor_channels[0] <= 15
        assert 0 <= motor_channels[1] <= 15
        assert -1.0 <= speed <= 1.0
        duty_cycle = int(abs(speed) * 0xffff)

        if speed >= 0: # forward
            self.pwm_hat.channels[motor_channels[1]].duty_cycle = 0x0000
            self.pwm_hat.channels[motor_channels[0]].duty_cycle = duty_cycle
        else: # backward
            self.pwm_hat.channels[motor_channels[0]].duty_cycle = 0x0000
            self.pwm_hat.channels[motor_channels[1]].duty_cycle = duty_cycle

    def move_doors(self, door_idx: int, set_pos: float):
        '''
        Takes in the door index and the set position in mm
        Runs until the door reaches the set position within tolerance
        (Thread safe with encoder updates)
        '''
        assert 0 <= door_idx < len(self.door_motor_channels)
        assert 0 <= set_pos <= self.max_door_pos

        motor = self.door_motor_channels[door_idx]
        in_range = False

        while not in_range:
            if self.door_pos[door_idx] < set_pos:
                motor.throttle = 1.0
            else:
                motor.throttle = -1.0

            # with self.enc_lock:
            #     if (set_pos - self.door_tol < self.door_pos[door_idx] < set_pos + self.door_tol):
            #         in_range = True

            # In place of encoders:
            travel_time = 0.01 # seconds per mm
            time.sleep(travel_time*abs(set_pos - self.door_pos[door_idx]))
            self.door_pos[door_idx] = set_pos
            in_range = True

        motor.throttle = 0.0

    def set_positions(self, group: str, positions: list[float]):
        '''
        Sets the internal position variables for the specified group.
        group: 'dividers', 'rails', or 'doors'
        positions: list of positions in mm
        '''
        if group == 'dividers':
            assert len(positions) == len(self.div_pos)
            with self.enc_lock:
                self.div_pos = positions.copy()
        elif group == 'rails':
            assert len(positions) == len(self.rail_pos)
            with self.enc_lock:
                self.rail_pos = positions.copy()
        elif group == 'doors':
            assert len(positions) == len(self.door_pos)
            with self.enc_lock:
                self.door_pos = positions.copy()
        else:
            print("Invalid group specified for set_positions")

    def _encoder_hat_thread(self):
        '''
        Thread function to continuously read encoder values
        and update the position variables.
        '''
        myEncoders = qwiic_dual_encoder_reader.QwiicDualEncoderReader()
        if myEncoders.connected == False:
            print("The Qwiic Dual Encoder Reader device isn't connected to the system. Please check your connection", \
                file=sys.stderr)
            return

        myEncoders.begin()

        cts_init = None
        while True:
            ct1 = myEncoders.count1
            ct2 = myEncoders.count2

            if cts_init is None:
                cts_init = (ct1, ct2)
                continue

            with self.enc_lock:
                # Update divider positions
                # Motors are 1/455 gear ratio, driving a lead screw with 8mm travel per revolution (2mm pitch, 4 starts)
                self.div_pos[0] = (ct1-cts_init[0])*(8.0 / 455.0)
                self.div_pos[1] = (ct2-cts_init[1])*(8.0 / 455.0)
    
    def _encoder_serial_thread(self):
        '''
        Thread function to continuously read encoder values
        from serial and update the position variables.
        format of serial line: "enc<#>: <count>"
        '''
        import serial

        ser = serial.Serial('/dev/serial0', 921600, timeout = 0.2)
        print("Reading Encoders...")

        # Encoders have 3 counts per revolution
        # Motors are 1/455 gear ratio
        # Resulting in 5,462.22 per revolution
        # Lead screw with 8mm travel per revolution (2mm pitch, 4 starts)
        # Resulting in 682.78 counts per mm travel

        cts_init = {}
        encoders = {}
        num_encoders = 4
        full_init = False
        while True:
            line = ser.readline().decode("ascii", errors="ignore").strip()
            if not line:
                continue

            try:
                key, value = line.split(":")
                num = key.strip()
                ct = int(value.strip())
                encoders[num] = ct

                #print(encoders)
                if not full_init:
                    if cts_init.get(num, -1) < 0:
                        cts_init[num] = ct
                    if len(cts_init) == num_encoders:
                        full_init = True
                        print("Encoder initialization complete.")

            except ValueError:
                pass
            
            i = 0
            with self.enc_lock:
                for num in cts_init.keys():
                    self.rail_pos[i] = (encoders[num]-cts_init[num]) / 682.78
                    i += 1


