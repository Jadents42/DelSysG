import board
import busio
import adafruit_pca9685
from adafruit_servokit import ServoKit
import threading
import serial
import csv
from time import sleep
from datetime import datetime

class SystemG():
    def __init__(self):
        self.partitions_idx = [1, 2, 3]
        self.max_div_pos = 800 # mm 
        self.max_rail_pos = 280 # mm 
        self.max_door_pos = 250 # mm 
        self.div_tol = 0.5 # mm
        self.rail_tol = 0.5 # mm
        self.door_tol = 2 # mm
        self.rail_width = 24 # mm
        pos_file = "/home/cmrl/Software/DelSysG/systemG_positions.csv"

        print("System G: Initializing Hardware...")
        # Initialize I2C bus
        I2C = busio.I2C(board.SCL, board.SDA)

        # PWM Pi Hat channels
        self.pwm_hat = adafruit_pca9685.PCA9685(i2c_bus=I2C, address=0x41)
        self.pwm_hat.frequency = 1500
        # Motor channels for [rail 0, rail 1, rail 2, rail 3]
        self.rail_motor_channels = [(0, 1), (2, 3), (4, 5), (6, 7)]
        # Motor channels for [divider 1, divider 2]
        self.divider_motor_channels = [(8, 9), (10, 11)]

        # Servo Driver for Autohat
        self.servo_hat = ServoKit(channels=16, i2c=I2C, address=0x40)
        # Servo channels for [rail 0, rail 1, rail 2, rail 3]
        self.servo_channels = [0, 1, 2, 3]
        self.engaged = [False]*len(self.servo_channels)

        # Tuned center positions for Servos
        self.servo_centers = {
            0: 135,  # Channel 0 (Servo 1)
            1: 120,  # Channel 1 (Servo 2)
            2: 90,  # Channel 2 (Servo 3)
            3: 95   # Channel 3 (Servo 4)
        }
        # DC + Stepper Motor Pi Hat channels
        self.stm_ser = serial.Serial('/dev/serial0', 921600, timeout=.2)

        # Load positions
        self.rail_pos = self.door_pos = self.div_pos = None
        if not self.load_positions_from_csv(pos_file):
            print("No position file found. Please update the positions manually.")
            exit(1)

        # Center (Disengage) all servos
        print("Disengaging all servos...")
        for ch in self.servo_channels:
            self.servo_hat.servo[ch].actuation_range = 270
            self.servo_hat.servo[ch].set_pulse_width_range(500, 2500)
            # Moves servo positions to center
            self.servo_hat.servo[ch].angle = self.servo_centers[ch]
            sleep(1)

        # Limit switch states from STM32 [lim1, lim2, lim3, lim4] on pins [A6, A5, A1, A0]
        # True = pressed. None until the first "lim" line arrives.
        self.limit_switches = None

        # Start encoder reading and position saving threads
        self.stm_lock = threading.Lock()
        self.enc_thread = threading.Thread(target=self._encoder_serial_thread, daemon=True)
        self.save_thread = threading.Thread(target=self._position_saver_thread, daemon=True, args=(pos_file, 1.0))
        self.enc_thread.start()
        self.save_thread.start()

        print("System Initialized.")


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

        # if div_idx == 1:
        #     if set_pos > self.div_pos[1] - self.div_tol - self.rail_width:
        #         print("Divider 1 cannot move beyond Divider 2")
        #         return
        
        # if div_idx == 2:
        #     if set_pos < self.div_pos[0] + self.div_tol + self.rail_width:
        #         print("Divider 2 cannot move beyond Divider 1")
        #         return
        
        div_idx -= 1
        
        assert div_idx >= 0
        assert div_idx < len(self.divider_motor_channels)
        #assert 0 <= set_pos <= self.max_div_pos

        ch = self.divider_motor_channels[div_idx]
        in_range = False

        while not in_range:
            if self.div_pos[div_idx] < set_pos:
                self.drive_pwm_motor(ch, -1.0)
            else:
                self.drive_pwm_motor(ch, 1.0)

            sleep(0.05)
            with self.stm_lock:
                if (set_pos - self.div_tol < self.div_pos[div_idx] < set_pos + self.div_tol):
                    in_range = True
            #print(f"Divider position: {self.div_pos[div_idx]} mm")
        
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

            sleep(0.05)
            with self.stm_lock:
                if (set_pos - self.rail_tol < self.rail_pos[part_idx] < set_pos + self.rail_tol):
                    r_in_range = True
                if (set_pos - self.rail_tol < self.rail_pos[part_idx - 1] < set_pos + self.rail_tol):
                    l_in_range = True
            #print(f"Rail positions: [{self.rail_pos[part_idx]}, {self.rail_pos[part_idx - 1]}] mm")
        
        self.drive_pwm_motor(r_ch, 0.0)
        self.drive_pwm_motor(l_ch, 0.0)

    def engage_pushers(self, part_idx: int, engage: bool = True, angle: int = 60):
        '''
        Takes in the partition index and whether to engage (True) or disengage (False)
        Turns the servos to the appropriate angle
        '''
        if part_idx not in self.partitions_idx:
            print("Invalid partition referenced")
            print(f"{part_idx} is not in {self.partitions_idx}")
            return
        
        assert 0 < part_idx < len(self.servo_channels)
        left_ch = self.servo_channels[part_idx - 1]
        right_ch = self.servo_channels[part_idx]

        if angle == 0:
            engage = False
        if not engage:
            angle = 0

        # Left servo
        self.servo_hat.servo[left_ch].angle = self.servo_centers[left_ch] - angle
        self.engaged[left_ch] = engage
        sleep(1)
        # Right servo 
        self.servo_hat.servo[right_ch].angle = self.servo_centers[right_ch] + angle
        self.engaged[right_ch] = engage

        #print(f"Servo angles: [{-angle}, {angle}] deg")

    
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
            self.pwm_hat.channels[motor_channels[0]].duty_cycle = 0x0000
            self.pwm_hat.channels[motor_channels[1]].duty_cycle = duty_cycle
        else: # backward
            self.pwm_hat.channels[motor_channels[1]].duty_cycle = 0x0000
            self.pwm_hat.channels[motor_channels[0]].duty_cycle = duty_cycle

    def move_door(self, door_idx: int, set_pos: float):
        '''
        Takes in the door index and the set position in mm
        Runs until the door reaches the set position within tolerance
        '''
        door_idx -= 1
        assert 0 <= door_idx < len(self.door_pos)
        
        start_pos = self.door_pos[door_idx]
        total_dist = set_pos - start_pos
        
        if abs(total_dist) < 0.1:
            return 0
            
        # Paced mm increments to let the motor move without high-freq choking
        step_increment = 4.0 if total_dist > 0 else -4.0
        current_pos = start_pos
        
        while True:
            if abs(set_pos - current_pos) <= abs(step_increment):
                current_pos = set_pos
            else:
                current_pos += step_increment
                
            dist_to_move = current_pos - self.door_pos[door_idx]
            # Correct math including the * 8 microstepping factor
            num_steps = int(dist_to_move / 150 * 1.0 * 200 * 8)
            
            message = f"step{door_idx+1}: {num_steps}\n"
            self.stm_ser.write(message.encode())
            
            self.door_pos[door_idx] = current_pos
            if current_pos == set_pos:
                break
                
            sleep(0.08) # Relaxed delay so serial interrupts don't starve the STM32 timer
            
        return num_steps
    
    def jiggle_motors(self):
        '''
        Jiggling all motors to prevent stalling.
        '''
        # Jiggle divider motors
        for ch in self.divider_motor_channels:
            self.drive_pwm_motor(ch, 0.5)
            sleep(0.1)
            self.drive_pwm_motor(ch, -0.5)
            sleep(0.1)
            self.drive_pwm_motor(ch, 0.0)
        
        # Jiggle rail motors
        for ch in self.rail_motor_channels:
            self.drive_pwm_motor(ch, 0.5)
            sleep(0.1)
            self.drive_pwm_motor(ch, -0.5)
            sleep(0.1)
            self.drive_pwm_motor(ch, 0.0)
    
    def stop_motion(self):
        '''
        Stops all motion by sending zero speed to all motors and aborting STM32 steps.
        '''
        # Stop divider motors
        for ch in self.divider_motor_channels:
            self.drive_pwm_motor(ch, 0.0)
        
        # Stop rail motors
        for ch in self.rail_motor_channels:
            self.drive_pwm_motor(ch, 0.0)

        # Stop Door Steppers (STM32)
        try:
            self.stm_ser.write(b"step1: 0\n")
            self.stm_ser.write(b"step2: 0\n")
        except Exception:
            pass

    def set_positions(self, group: str, positions: list[float]):
        '''
        Sets the internal position variables for the specified group.
        group: 'dividers', 'rails', or 'doors'
        positions: list of positions in mm
        '''
        if group == 'dividers':
            assert len(positions) == len(self.div_pos)
            with self.stm_lock:
                self.div_pos = positions.copy()
        elif group == 'rails':
            assert len(positions) == len(self.rail_pos)
            with self.stm_lock:
                self.rail_pos = positions.copy()
        elif group == 'doors':
            assert len(positions) == len(self.door_pos)
            with self.stm_lock:
                self.door_pos = positions.copy()
        else:
            print("Invalid group specified for set_positions")

    def get_positions(self):
        '''
        Returns the current positions of dividers, rails, and doors.
        '''
        with self.stm_lock:
            div_copy = self.div_pos.copy()
            rail_copy = self.rail_pos.copy()
            door_copy = self.door_pos.copy()
        return {
            "dividers": div_copy,
            "rails": rail_copy,
            "doors": door_copy
        }

    def get_limit_switches(self):
        '''
        Returns the limit switch states [lim1, lim2, lim3, lim4] (True = pressed),
        or None if no "lim" line has been received from the STM32 yet.
        '''
        with self.stm_lock:
            return None if self.limit_switches is None else self.limit_switches.copy()


    def load_positions_from_csv(self, filename):
        """
        Loads the most recent divider, rail, and door positions from a CSV file.
        """

        with open(filename, mode='r', newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            if not rows:
                return False

            last_row = rows[-1]

            # load values
            self.div_pos = [
                float(last_row["divider_1"]),
                float(last_row["divider_2"])
            ]

            self.rail_pos = [
                float(last_row["rail_0"]),
                float(last_row["rail_1"]),
                float(last_row["rail_2"]),
                float(last_row["rail_3"])
            ]

            self.door_pos = [
                float(last_row["door_left"]),
                float(last_row["door_right"])
            ]
        return True

    
    def _encoder_serial_thread(self):
        '''
        Thread function to continuously read encoder values
        from serial and update the position variables.
        format of serial line: "enc<#>: <count>"
        limit switch line: "lim: <s1>,<s2>,<s3>,<s4>" (1 = pressed)
        '''
        #print("Reading Encoders...")

        # Encoders have 3 counts per revolution
        # Motors are 1/455 gear ratio
        # Resulting in 5,462.22 per revolution
        # Lead screw with 8mm travel per revolution (2mm pitch, 4 starts)
        # Resulting in 682.78 counts per mm travel

        encoders = {}
        cts_init = {}
        r0_pos = self.rail_pos.copy()
        d0_pos = self.div_pos.copy()
        num_encoders = 6
        full_init = False
        while True:
            line = self.stm_ser.readline().decode("ascii", errors="ignore").strip()
            if not line:
                continue

            try:
                key, value = line.split(":")
                num = key.strip()

                if num == "lim":
                    states = [v.strip() == "1" for v in value.split(",")]
                    if len(states) == 4:
                        with self.stm_lock:
                            self.limit_switches = states
                    continue

                if not num.startswith("enc"):
                    continue
                ct = int(value.strip())
                encoders[num] = ct

            except ValueError:
                continue

            if cts_init.get(num, None) is None:
                cts_init[num] = ct
                if not full_init and len(cts_init) == num_encoders:
                    full_init = True
                    print("Encoder initialization complete.")

            idx = int(num[-1]) - 1
            if idx < 4:
                with self.stm_lock:
                    self.rail_pos[idx] = (encoders[num] - cts_init[num]) / 682.78 + r0_pos[idx]
            elif idx < 6:
                with self.stm_lock:
                    self.div_pos[idx - 4] = -(encoders[num] - cts_init[num]) / 682.78 + d0_pos[idx - 4]


    def _position_saver_thread(self, filename, period):
        """
        Thread function that logs divider, rail, and door positions to a CSV file.

        Args:
            filename (str): Path to CSV file
            period (float): Time interval between logs in seconds
        """

        # Open file once and keep appending
        with open(filename, mode='w', newline='') as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow([
                "timestamp",
                "divider_1", "divider_2",
                "rail_0", "rail_1", "rail_2", "rail_3",
                "door_left", "door_right"
            ])

            while True:
                timestamp = datetime.now().isoformat()

                with self.stm_lock:
                    row = [
                        timestamp,
                        self.div_pos[0], self.div_pos[1],
                        self.rail_pos[0], self.rail_pos[1],
                        self.rail_pos[2], self.rail_pos[3],
                        self.door_pos[0], self.door_pos[1]
                    ]

                writer.writerow(row)
                f.flush()   # ensure data is written even if program exits
                sleep(period)


if __name__ == "__main__":
    print("Initializing System G")
    sys = SystemG()
    sleep(2) # Allow threads to start

    print("Current Positions:")
    print(f"Dividers: {sys.div_pos}")
    print(f"Rails: {sys.rail_pos}")
    print(f"Doors: {sys.door_pos}")
