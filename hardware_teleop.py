#!/usr/bin/env python3
import sys
import select
import termios
import tty
import time

# Import Micah's hardware architecture for position tracking and motor encoders
from systemG_arch import SystemG

# evdev reads raw press/release events straight from the kernel keyboard device,
# giving true key-held state for jogging instead of inferring it from terminal
# key-repeat timing. Optional: falls back to keystroke-timing jog if unavailable.
try:
    import evdev
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False

# KEY MAP CONSTANTS
ARROW_UP = '\x1b[A'
ARROW_DOWN = '\x1b[B'
ARROW_RIGHT = '\x1b[C'
ARROW_LEFT = '\x1b[D'

# Software Position Limits for Safety
LIMITS = {
    'door_1':    {'min': 0.0, 'max': 2000.0, 'step': 5.0}, 
    'door_2':    {'min': 0.0, 'max': 2000.0, 'step': 5.0}, 
    'divider_1': {'min': -300.0, 'max': 2000.0, 'step': 5.0},
    'divider_2': {'min': 0.0, 'max': 2000.0, 'step': 5.0},
    'pusher_1':  {'min': 0.0, 'max': 2000.0, 'step': 5.0}, 
    'pusher_2':  {'min': 0.0, 'max': 2000.0, 'step': 5.0}, 
    'pusher_3':  {'min': 0.0, 'max': 2000.0, 'step': 5.0}, 
    'pusher_4':  {'min': 0.0, 'max': 2000.0, 'step': 5.0}, 
    'servo_1':   {'min': 0.0, 'max': 270.0, 'step': 5.0}, 
    'servo_2':   {'min': 0.0, 'max': 270.0, 'step': 5.0}, 
    'servo_3':   {'min': 0.0, 'max': 270.0, 'step': 5.0}, 
    'servo_4':   {'min': 0.0, 'max': 270.0, 'step': 5.0},
}

# Duty cycle for a single pusher jog pulse.
JOG_PULSE_DUTY = 1.0

if EVDEV_AVAILABLE:
    ARROW_EVDEV_MAP = {
        evdev.ecodes.KEY_UP: 'UP',
        evdev.ecodes.KEY_DOWN: 'DOWN',
        evdev.ecodes.KEY_LEFT: 'LEFT',
        evdev.ecodes.KEY_RIGHT: 'RIGHT',
    }

class HardwareTeachPendant:
    def __init__(self):
        print("Initializing MARCO Hardware Interface... Please wait 3 seconds.")
        self.sysG = SystemG()
        time.sleep(3) 

        self.current_mode = 'MAIN'
        self.selected_target = None 
        self.combined_mode = False  # Track combined mode state
        self.alert_message = ""
        self.settings = termios.tcgetattr(sys.stdin)
        self.last_ui_update = 0

        # Continuous-hold pusher jog state: rail_idx -> {'direction': int, 'last_seen': float}.
        # A rail stays driving (no intermediate brake) as long as jog commands for it keep
        # arriving within RAIL_JOG_HOLD_WINDOW; once they stop (key released) it gets braked.
        self.active_rail_jog = {}
        self.RAIL_JOG_HOLD_WINDOW = 0.35  # seconds

        # Continuous-hold divider jog state: div_idx -> {'direction': int, 'last_seen': float}.
        # Only ever populated when a real keyboard device is available (see _update_divider_jog) -
        # without one, dividers keep the original move_divider()-per-keystroke behavior untouched.
        self.active_divider_jog = {}

        # Raw keyboard device for true arrow-key press/release state (pusher + divider jog).
        # None means evdev/device unavailable - jog falls back to the original per-keystroke behavior.
        self.kbd_dev = None
        self.arrow_held = {'UP': False, 'DOWN': False, 'LEFT': False, 'RIGHT': False}
        if EVDEV_AVAILABLE:
            dev_path = self._find_keyboard_device()
            if dev_path:
                try:
                    self.kbd_dev = evdev.InputDevice(dev_path)
                    print(f"Jog input: reading raw key events from '{self.kbd_dev.name}' ({dev_path})")
                except OSError as e:
                    print(f"Jog input: could not open {dev_path} ({e}); falling back to keystroke-timing jog.")
            else:
                print("Jog input: no keyboard device found; falling back to keystroke-timing jog.")
        else:
            print("Jog input: 'evdev' not installed; falling back to keystroke-timing jog.")

        with self.sysG.stm_lock:
            d_pos = self.sysG.door_pos.copy()
            div_pos = self.sysG.div_pos.copy()
            r_pos = self.sysG.rail_pos.copy()
            
        self.desired = {
            'door_1': d_pos[0], 'door_2': d_pos[1],
            'divider_1': div_pos[0], 'divider_2': div_pos[1],
            'pusher_1': r_pos[0], 'pusher_2': r_pos[1], 'pusher_3': r_pos[2], 'pusher_4': r_pos[3],
            'servo_1': 135.0, 'servo_2': 120.0, 'servo_3': 90.0, 'servo_4': 95.0 # servo start position
        }

    def get_key(self):
        tty.setraw(sys.stdin.fileno())
        watch = [sys.stdin]
        if self.kbd_dev is not None:
            watch.append(self.kbd_dev)
        rlist, _, _ = select.select(watch, [], [], 0.05)

        if self.kbd_dev is not None and self.kbd_dev in rlist:
            self._drain_arrow_events()

        if sys.stdin in rlist:
            key = sys.stdin.read(1)
            if key == '\x1b':
                additional_chars = sys.stdin.read(2)
                key += additional_chars
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.settings)
            return key
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.settings)
        return None

    @staticmethod
    def _find_keyboard_device():
        '''Returns the /dev/input/eventX path of the first device with full keyboard
        capabilities (letters + arrow keys), skipping mice and HDMI-CEC pseudo-devices.'''
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            caps = dev.capabilities().get(evdev.ecodes.EV_KEY, [])
            if evdev.ecodes.KEY_A in caps and evdev.ecodes.KEY_Z in caps and evdev.ecodes.KEY_UP in caps:
                return path
        return None

    def _drain_arrow_events(self):
        try:
            for event in self.kbd_dev.read():
                if event.type == evdev.ecodes.EV_KEY and event.code in ARROW_EVDEV_MAP:
                    # value: 0=release, 1=press, 2=autorepeat (both press/autorepeat mean "held")
                    self.arrow_held[ARROW_EVDEV_MAP[event.code]] = (event.value != 0)
        except BlockingIOError:
            pass
        except OSError as e:
            self.alert_message = f"Keyboard device lost ({e}); pusher jog falling back to keystroke timing."
            self.kbd_dev = None
            self.arrow_held = {k: False for k in self.arrow_held}

    def display_ui(self, force=False):
        now = time.time()
        if not force and (now - self.last_ui_update < 0.1):
            return
        self.last_ui_update = now

        with self.sysG.stm_lock:
            d_pos = self.sysG.door_pos
            div_pos = self.sysG.div_pos
            r_pos = self.sysG.rail_pos

        sys.stdout.write("\033[2J\033[H") # Clearing and Flushing the Terminal
        sys.stdout.flush() 

        print("==========================================================================")
        print("           MARCO DELIVERY SYSTEM - HARDWARE POSIITION TRACKING                   ")
        print("==========================================================================")
        print(f" {'DEVICE':<15} | {'CURRENT POS (Live)':<22} | {'DESIRED TARGET':<22}")
        print("--------------------------------------------------------------------------")
        print(f" Door 1          | {d_pos[0]:<19.1f} mm | {self.desired['door_1']:<19.1f} mm")
        print(f" Door 2          | {d_pos[1]:<19.1f} mm | {self.desired['door_2']:<19.1f} mm")
        print(f" Divider 1       | {div_pos[0]:<19.1f} mm | {self.desired['divider_1']:<19.1f} mm")
        print(f" Divider 2       | {div_pos[1]:<19.1f} mm | {self.desired['divider_2']:<19.1f} mm")
        print(f" Pusher 1        | {r_pos[0]:<19.1f} mm | {self.desired['pusher_1']:<19.1f} mm")
        print(f" Pusher 2        | {r_pos[1]:<19.1f} mm | {self.desired['pusher_2']:<19.1f} mm")
        print(f" Pusher 3        | {r_pos[2]:<19.1f} mm | {self.desired['pusher_3']:<19.1f} mm")
        print(f" Pusher 4        | {r_pos[3]:<19.1f} mm | {self.desired['pusher_4']:<19.1f} mm")
        print(f" Servo 1         | {self.desired['servo_1']:<19.1f} °  | {self.desired['servo_1']:<19.1f} °")
        print(f" Servo 2         | {self.desired['servo_2']:<19.1f} °  | {self.desired['servo_2']:<19.1f} °")
        print(f" Servo 3         | {self.desired['servo_3']:<19.1f} °  | {self.desired['servo_3']:<19.1f} °")
        print(f" Servo 4         | {self.desired['servo_4']:<19.1f} °  | {self.desired['servo_4']:<19.1f} °")
        print("==========================================================================")
        
        if self.alert_message:
            print(f"\033[91mALERT: {self.alert_message:<50}\033[0m")
            print("--------------------------------------------------------------------------")
            self.alert_message = ""
        else:
            print(f"{'':<74}") 
            print("--------------------------------------------------------------------------")

        if self.current_mode == 'MAIN':
            print(" Select Device Type to Manage:                          ")
            print("   [Q] Push Arms                                            ")
            print("   [W] Servos                                         ")
            print("   [E] Dividers                                        ")
            print("   [R] Doors                                           ")
            print("\n System Controls:                                     ")
            print("   [X] EMERGENCY STOP MOTORS                            ")
            print("   [Z] Quit Program                                     ")

        elif self.current_mode == 'DOORS':
            print("\033[96m MODE: DOORS CONTROL (HIGH TORQUE FULL STEP)\033[0m          ")
            print(" Select Unit: [1] Left Door  |  [2] Right Door          ")
            if self.selected_target:
                print(f" Current Focus: \033[92m{self.selected_target.upper()}\033[0m                ")
                print(" Controls: [Up/Down Arrows] Step Live (+/- 5mm)         ")
                print("           [A] Enter absolute target to drive to        ")
            print("\n [Spacebar] Main Menu  |  [X] STOP MOTORS               ")

        elif self.current_mode == 'DIVIDERS':
            print("\033[96m MODE: DIVIDER CONTROL\033[0m                      ")
            print(" Select Unit: [1] DIVIDER 1  |  [2] DIVIDER 2       ")
            if self.selected_target:
                print(f" Current Focus: \033[92m{self.selected_target.upper()}\033[0m                ")
                print(" Controls: [Left/Right Arrows] Step Live (+/- 5mm)     ")
                print("           [A] Enter absolute target to drive to        ")
                if self.kbd_dev is not None:
                    print(f" [DEBUG] arrow_held: LEFT={self.arrow_held['LEFT']}  RIGHT={self.arrow_held['RIGHT']}   "
                          f"active_divider_jog: {self.active_divider_jog}")
            print("\n [Spacebar] Main Menu  |  [X] STOP MOTORS               ")

        elif self.current_mode == 'PUSHERS':
            print("\033[96m MODE: PUSH ARMS CONTROL\033[0m                               ")
            print(" Select Unit: [1] Pusher 1 | [2] Pusher 2 | [3] Pusher 3 | [4] Pusher 4")
            print("              [C] Toggle Combined Mode")
            if self.combined_mode:
                print(" \033[93m *COMBINED MODE ACTIVE*: Select pair: [1] (1&2), [2] (2&3), [3] (3&4)\033[0m")
            if self.selected_target:
                print(f" Current Focus: \033[92m{self.selected_target.upper()}\033[0m                ")
                print(" Controls: [Up/Down Arrows] Step Live (+/- 5mm)      ")
                print("           [A] Enter absolute target to drive to        ")
            print("\n [Spacebar] Main Menu  |  [X] STOP MOTORS               ")

        elif self.current_mode == 'SERVOS':
            print("\033[96m📁 MODE: SERVO CONTROL\033[0m                        ")
            print(" Select Unit: [1] Servo 1 | [2] Servo 2 | [3] Servo 3 | [4] Servo 4")
            print("              [C] Toggle Combined Mode")
            if self.combined_mode:
                print(" \033[93m*COMBINED MODE ACTIVE*: Select pair: [1] (1&2), [2] (2&3), [3] (3&4)\033[0m")
            if self.selected_target:
                print(f" Current Focus: \033[92m{self.selected_target.upper()}\033[0m                ")
                print(" Controls: [Left/Right Arrows] Step Live Angle (+/- 5°) ")
                if self.combined_mode:
                    print("           (Mirrored Grabbing Motion)                   ")
            print("\n [Spacebar] Main Menu  |  [X] STOP MOTORS               ")

        sys.stdout.flush()

    def execute_hardware_jog(self, joint_key, direction):
        if 'comb' not in joint_key:
            cfg = LIMITS[joint_key]
            target_pos = self.desired[joint_key] + (direction * cfg['step'])
            target_pos = max(cfg['min'], min(target_pos, cfg['max']))
            self.desired[joint_key] = target_pos
            self.alert_message = f"Commanding {joint_key} to {target_pos}..."
        else:
            self.alert_message = f"Commanding combined {joint_key}..."

        self.display_ui(force=True)

        try:
            if 'door' in joint_key:
                idx = int(joint_key.split('_')[1])
                # Direct call to the architecture file with correct math!
                self.sysG.move_door(idx, target_pos)
                
            elif 'divider' in joint_key:
                idx = int(joint_key.split('_')[1])
                self.sysG.move_divider(idx, target_pos)
                
            elif 'pusher_comb' in joint_key:
                comb_idx = int(joint_key.split('_')[2])
                idx1 = comb_idx - 1
                idx2 = comb_idx
                cfg = LIMITS['pusher_1']
                
                t1 = self.desired[f"pusher_{idx1+1}"] + (direction * cfg['step'])
                t2 = self.desired[f"pusher_{idx2+1}"] + (direction * cfg['step'])
                
                t1 = max(cfg['min'], min(t1, cfg['max']))
                t2 = max(cfg['min'], min(t2, cfg['max']))
                
                self.desired[f"pusher_{idx1+1}"] = t1
                self.desired[f"pusher_{idx2+1}"] = t2

                self._drive_rail_jog(idx1, direction)
                self._drive_rail_jog(idx2, direction)

            elif 'pusher' in joint_key:
                idx = int(joint_key.split('_')[1])
                self._drive_rail_jog(idx - 1, direction)


            elif 'servo_comb' in joint_key:
                comb_idx = int(joint_key.split('_')[2])
                idx1 = comb_idx - 1
                idx2 = comb_idx
                cfg = LIMITS['servo_1']
                
                # Grabbing motion: Mirrored (- direction for left, + direction for right)
                t1 = self.desired[f"servo_{idx1+1}"] - (direction * cfg['step'])
                t2 = self.desired[f"servo_{idx2+1}"] + (direction * cfg['step'])
                
                t1 = max(cfg['min'], min(t1, cfg['max']))
                t2 = max(cfg['min'], min(t2, cfg['max']))
                
                self.desired[f"servo_{idx1+1}"] = t1
                self.desired[f"servo_{idx2+1}"] = t2
                
                if hasattr(self.sysG, 'servo_hat'):
                    self.sysG.servo_hat.servo[idx1].angle = t1
                    self.sysG.servo_hat.servo[idx2].angle = t2
                    
            elif 'servo' in joint_key:
                idx = int(joint_key.split('_')[1]) - 1
                if hasattr(self.sysG, 'servo_hat'):
                    self.sysG.servo_hat.servo[idx].angle = target_pos
                    
        except Exception as e:
            self.alert_message = f"HW Error on {joint_key}: {e}"

        termios.tcflush(sys.stdin, termios.TCIFLUSH) #flushing the keyboard input

    def _drive_channel_jog(self, active_dict, idx, ch_tuple, direction):
        '''
        Applies (or re-applies) drive to a motor channel pair for a jog keystroke, without
        braking first. Marks it "actively held" in active_dict so a staleness check (fallback
        path) knows to keep it running until the repeat keystrokes stop (key released).
        direction > 0 always drives ch_tuple[0]; this convention is shared by rails and
        dividers - see _drive_divider_jog for how the divider sign was derived.
        '''
        pwm_val = int(JOG_PULSE_DUTY * 65535)

        try:
            if direction > 0:
                self.sysG.pwm_hat.channels[ch_tuple[0]].duty_cycle = pwm_val
                self.sysG.pwm_hat.channels[ch_tuple[1]].duty_cycle = 0
            else:
                self.sysG.pwm_hat.channels[ch_tuple[0]].duty_cycle = 0
                self.sysG.pwm_hat.channels[ch_tuple[1]].duty_cycle = pwm_val
        except OSError as e:
            # I2C write failed (e.g. a bus fault on this channel) - don't crash the whole
            # pendant over it. Don't track it as active, and best-effort try to brake it
            # (which may also fail if the bus is in a bad state - that's what E-stop is for).
            self.alert_message = f"I2C write failed on channels {ch_tuple} ({e}); braking."
            active_dict.pop(idx, None)
            self._brake_channel(ch_tuple)
            return

        active_dict[idx] = {'direction': direction, 'last_seen': time.time()}

    def _brake_channel(self, ch_tuple):
        try:
            self.sysG.pwm_hat.channels[ch_tuple[0]].duty_cycle = 0
            self.sysG.pwm_hat.channels[ch_tuple[1]].duty_cycle = 0
        except OSError as e:
            self.alert_message = f"I2C write failed while braking channels {ch_tuple} ({e})! Hit X for E-STOP."

    def _drive_rail_jog(self, rail_idx, direction):
        self._drive_channel_jog(self.active_rail_jog, rail_idx, self.sysG.rail_motor_channels[rail_idx], direction)

    def _brake_rail(self, rail_idx):
        self._brake_channel(self.sysG.rail_motor_channels[rail_idx])

    def _release_stale_rail_jogs(self):
        '''
        Called every main-loop tick. Brakes any rail whose jog keystroke hasn't repeated
        within RAIL_JOG_HOLD_WINDOW - the signal that the key was actually released.
        '''
        now = time.time()
        stale = [idx for idx, info in self.active_rail_jog.items()
                 if now - info['last_seen'] > self.RAIL_JOG_HOLD_WINDOW]
        for idx in stale:
            self._brake_rail(idx)
            del self.active_rail_jog[idx]

    def _brake_all_active_rail_jogs(self):
        for idx in list(self.active_rail_jog.keys()):
            self._brake_rail(idx)
        self.active_rail_jog.clear()

    def _drive_divider_jog(self, div_idx, direction):
        '''
        direction > 0 (RIGHT, increasing div_pos) drives ch_tuple[0] - derived from
        move_divider()'s own proven-working logic in systemG_arch.py: to increase div_pos
        it calls drive_pwm_motor(ch, -1.0), whose "backward" branch drives channel[0].
        Same convention as _drive_rail_jog, so it reuses the same shared helper.
        '''
        self._drive_channel_jog(self.active_divider_jog, div_idx, self.sysG.divider_motor_channels[div_idx], direction)

    def _brake_divider(self, div_idx):
        self._brake_channel(self.sysG.divider_motor_channels[div_idx])

    def _brake_all_active_divider_jogs(self):
        for idx in list(self.active_divider_jog.keys()):
            self._brake_divider(idx)
        self.active_divider_jog.clear()

    def _pusher_target_rail_indices(self):
        if not self.selected_target or 'pusher' not in self.selected_target:
            return []
        if 'comb' in self.selected_target:
            comb_idx = int(self.selected_target.split('_')[2])
            return [comb_idx - 1, comb_idx]
        idx = int(self.selected_target.split('_')[1])
        return [idx - 1]

    def _update_pusher_jog(self):
        '''
        Called every main-loop tick. When a real keyboard device is available, drives
        pushers directly off live arrow-key held-state (true press/release, no timing
        heuristic) instead of waiting for discrete jog keystrokes. Falls back to the
        keystroke-timing staleness check when no evdev device was found.
        '''
        if self.kbd_dev is None:
            self._release_stale_rail_jogs()
            return

        rail_idxs = set(self._pusher_target_rail_indices()) if self.current_mode == 'PUSHERS' else set()

        # Brake anything still driving that's no longer the selected pusher target
        # (mode switched, target changed, or we're not in PUSHERS mode at all).
        for idx in list(self.active_rail_jog.keys()):
            if idx not in rail_idxs:
                self._brake_rail(idx)
                del self.active_rail_jog[idx]

        if not rail_idxs:
            return

        if self.arrow_held['DOWN'] and not self.arrow_held['UP']:
            direction = 1
        elif self.arrow_held['UP'] and not self.arrow_held['DOWN']:
            direction = -1
        else:
            direction = 0

        if direction == 0:
            for idx in rail_idxs:
                if idx in self.active_rail_jog:
                    self._brake_rail(idx)
                    del self.active_rail_jog[idx]
            return

        with self.sysG.stm_lock:
            rail_pos_snapshot = {idx: self.sysG.rail_pos[idx] for idx in rail_idxs}

        for idx in rail_idxs:
            self._drive_rail_jog(idx, direction)
            self.desired[f"pusher_{idx + 1}"] = rail_pos_snapshot[idx]

    def _update_divider_jog(self):
        '''
        Called every main-loop tick. When a real keyboard device is available, drives the
        selected divider directly off live arrow-key held-state, same as pushers - except
        it also auto-brakes at LIMITS[...]['min'/'max'] even while the key is still held,
        preserving the auto-stop-at-limit behavior the old move_divider()-per-keystroke
        jog already gave you (that target-seeking loop would drive to, and stop at, a
        LIMITS-clamped target; pure "drive while held" has no target to stop at otherwise).
        When no evdev device was found, dividers are untouched: still the original
        move_divider()-per-keystroke behavior via execute_hardware_jog.
        '''
        if self.kbd_dev is None:
            return

        div_idx = None
        if self.current_mode == 'DIVIDERS' and self.selected_target and 'divider' in self.selected_target:
            div_idx = int(self.selected_target.split('_')[1]) - 1

        active_idxs = {div_idx} if div_idx is not None else set()

        # Brake anything still driving that's no longer the selected divider target
        # (mode switched, target changed, or we're not in DIVIDERS mode at all).
        for idx in list(self.active_divider_jog.keys()):
            if idx not in active_idxs:
                self._brake_divider(idx)
                del self.active_divider_jog[idx]

        if div_idx is None:
            return

        if self.arrow_held['RIGHT'] and not self.arrow_held['LEFT']:
            direction = 1
        elif self.arrow_held['LEFT'] and not self.arrow_held['RIGHT']:
            direction = -1
        else:
            direction = 0

        with self.sysG.stm_lock:
            curr = self.sysG.div_pos[div_idx]

        if direction != 0:
            cfg = LIMITS[self.selected_target]
            if (direction > 0 and curr >= cfg['max']) or (direction < 0 and curr <= cfg['min']):
                direction = 0  # already at the software limit - don't drive further even if held

        if direction == 0:
            if div_idx in self.active_divider_jog:
                self._brake_divider(div_idx)
                del self.active_divider_jog[div_idx]
            return

        self._drive_divider_jog(div_idx, direction)
        self.desired[self.selected_target] = curr

    def _move_absolute_isolated_rail(self, rail_idx, target_pos, timeout=600.0):
        ch_tuple = self.sysG.rail_motor_channels[rail_idx]
        start_time = time.time()

        while time.time() - start_time < timeout:
            key = self.get_key()
            if key and key.upper() == 'X':
                self.alert_message = "EMERGENCY STOP TRIGGERED!"
                self.sysG.pwm_hat.channels[ch_tuple[0]].duty_cycle = 0
                self.sysG.pwm_hat.channels[ch_tuple[1]].duty_cycle = 0
                self.sysG.stop_motion()
                self.current_mode = 'MAIN'
                self.selected_target = None
                return 
                
            with self.sysG.stm_lock:
                curr = self.sysG.rail_pos[rail_idx]
            
            error = target_pos - curr
            if abs(error) <= self.sysG.rail_tol:
                break 
                
            speed_mag = max(0.4, min(1.0, abs(error) * 0.1))
            speed = speed_mag if error > 0 else -speed_mag
            pwm_val = int(abs(speed) * 65535)
                
            if speed > 0:
                self.sysG.pwm_hat.channels[ch_tuple[0]].duty_cycle = pwm_val
                self.sysG.pwm_hat.channels[ch_tuple[1]].duty_cycle = 0
            else:
                self.sysG.pwm_hat.channels[ch_tuple[0]].duty_cycle = 0
                self.sysG.pwm_hat.channels[ch_tuple[1]].duty_cycle = pwm_val
                
            self.display_ui() 
            
        self.sysG.pwm_hat.channels[ch_tuple[0]].duty_cycle = 0
        self.sysG.pwm_hat.channels[ch_tuple[1]].duty_cycle = 0
        
        time.sleep(0.1)
        with self.sysG.stm_lock:
            joint_key = f"pusher_{rail_idx + 1}"
            self.desired[joint_key] = self.sysG.rail_pos[rail_idx]

    def _move_absolute_combined_rails(self, r1_idx, r2_idx, target_pos, timeout=600.0):
        ch1 = self.sysG.rail_motor_channels[r1_idx]
        ch2 = self.sysG.rail_motor_channels[r2_idx]
        start_time = time.time()

        while time.time() - start_time < timeout:
            key = self.get_key()
            if key and key.upper() == 'X':
                self.alert_message = "EMERGENCY STOP TRIGGERED!"
                self.sysG.pwm_hat.channels[ch1[0]].duty_cycle = 0
                self.sysG.pwm_hat.channels[ch1[1]].duty_cycle = 0
                self.sysG.pwm_hat.channels[ch2[0]].duty_cycle = 0
                self.sysG.pwm_hat.channels[ch2[1]].duty_cycle = 0
                self.sysG.stop_motion()
                self.current_mode = 'MAIN'
                self.selected_target = None
                return 
                
            with self.sysG.stm_lock:
                curr1 = self.sysG.rail_pos[r1_idx]
                curr2 = self.sysG.rail_pos[r2_idx]
            
            error1 = target_pos - curr1
            error2 = target_pos - curr2
            
            # Check if both rails have hit the target tolerance
            in_range1 = abs(error1) <= self.sysG.rail_tol
            in_range2 = abs(error2) <= self.sysG.rail_tol
            
            if in_range1 and in_range2:
                break 
                
            # Control Rail 1
            if not in_range1:
                speed_mag1 = max(0.4, min(1.0, abs(error1) * 0.1))
                speed1 = speed_mag1 if error1 > 0 else -speed_mag1
                pwm_val1 = int(abs(speed1) * 65535)
                if speed1 > 0:
                    self.sysG.pwm_hat.channels[ch1[0]].duty_cycle = pwm_val1
                    self.sysG.pwm_hat.channels[ch1[1]].duty_cycle = 0
                else:
                    self.sysG.pwm_hat.channels[ch1[0]].duty_cycle = 0
                    self.sysG.pwm_hat.channels[ch1[1]].duty_cycle = pwm_val1
            else:
                self.sysG.pwm_hat.channels[ch1[0]].duty_cycle = 0
                self.sysG.pwm_hat.channels[ch1[1]].duty_cycle = 0

            # Control Rail 2
            if not in_range2:
                speed_mag2 = max(0.4, min(1.0, abs(error2) * 0.1))
                speed2 = speed_mag2 if error2 > 0 else -speed_mag2
                pwm_val2 = int(abs(speed2) * 65535)
                if speed2 > 0:
                    self.sysG.pwm_hat.channels[ch2[0]].duty_cycle = pwm_val2
                    self.sysG.pwm_hat.channels[ch2[1]].duty_cycle = 0
                else:
                    self.sysG.pwm_hat.channels[ch2[0]].duty_cycle = 0
                    self.sysG.pwm_hat.channels[ch2[1]].duty_cycle = pwm_val2
            else:
                self.sysG.pwm_hat.channels[ch2[0]].duty_cycle = 0
                self.sysG.pwm_hat.channels[ch2[1]].duty_cycle = 0
                
            self.display_ui() 
            
        # Hard Brake Both
        self.sysG.pwm_hat.channels[ch1[0]].duty_cycle = 0
        self.sysG.pwm_hat.channels[ch1[1]].duty_cycle = 0
        self.sysG.pwm_hat.channels[ch2[0]].duty_cycle = 0
        self.sysG.pwm_hat.channels[ch2[1]].duty_cycle = 0
        
        time.sleep(0.1)
        with self.sysG.stm_lock:
            self.desired[f"pusher_{r1_idx + 1}"] = self.sysG.rail_pos[r1_idx]
            self.desired[f"pusher_{r2_idx + 1}"] = self.sysG.rail_pos[r2_idx]

def main():
    try:
        node = HardwareTeachPendant()
    except Exception as e:
        print(f"Failed to initialize hardware: {e}")
        return

    sys.stdout.write("\033[2J") 
    sys.stdout.write("\033[?225l") # Clearing the terminal of keystrokes

    try:
        while True:
            node.display_ui()
            node._update_pusher_jog()    # drive/brake pushers off live arrow-key state
            node._update_divider_jog()   # drive/brake divider off live arrow-key state
            key = node.get_key()

            if not key:
                continue

            if key == '\x03' or key.upper() == 'Z':
                node._brake_all_active_rail_jogs()
                node._brake_all_active_divider_jogs()
                break

            if key.upper() == 'X':
                node._brake_all_active_rail_jogs()
                node._brake_all_active_divider_jogs()
                node.sysG.stop_motion()
                node.current_mode = 'MAIN'
                node.selected_target = None
                node.combined_mode = False
                node.alert_message = "EMERGENCY STOP TRIGGERED. STM32 REBOOTED."
                continue

            if key.upper() in ['Q', 'W', 'E', 'R']:
                node._brake_all_active_rail_jogs()
                node._brake_all_active_divider_jogs()
                node.selected_target = None
                node.combined_mode = False
                if key.upper() == 'Q': node.current_mode = 'PUSHERS'
                if key.upper() == 'W': node.current_mode = 'SERVOS'
                if key.upper() == 'E': node.current_mode = 'DIVIDERS'
                if key.upper() == 'R': node.current_mode = 'DOORS'
                continue

            if key == ' ':
                node._brake_all_active_rail_jogs()
                node._brake_all_active_divider_jogs()
                node.current_mode = 'MAIN'
                node.selected_target = None
                node.combined_mode = False
                continue

            if node.current_mode == 'DOORS':
                if key in ['1', '2']: node.selected_target = f"door_{key}"
                elif node.selected_target:
                    if key == ARROW_UP:      node.execute_hardware_jog(node.selected_target, 1)
                    elif key == ARROW_DOWN:  node.execute_hardware_jog(node.selected_target, -1)
                    
                    elif key.upper() == 'A':
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, node.settings)
                        print(f"\r\n[INPUT] Target for {node.selected_target.upper()} (mm) [Enter to Cancel / X for E-Stop]: ", end="")
                        val_str = input().strip().lower()
                        tty.setraw(sys.stdin.fileno()) 
                        
                        if val_str in ['', 'c']:
                            node.alert_message = "Move cancelled."
                            continue
                        if val_str == 'x':
                            node.sysG.stop_motion()
                            node.current_mode = 'MAIN'
                            node.selected_target = None
                            node.alert_message = "E-STOP TRIGGERED FROM MENU."
                            continue
                            
                        try:
                            val = float(val_str)
                            idx = int(node.selected_target.split('_')[1])
                            dist = val - node.sysG.door_pos[idx - 1]
                            
                            num_steps = int(dist / 150 * 1 * 200 * 1) 
                            
                            node.alert_message = f"Blasting {num_steps} steps to {node.selected_target}!"
                            node.sysG.stm_ser.write(f"step{idx}: {num_steps}\n".encode())
                            node.desired[node.selected_target] = val
                        except ValueError:
                            node.alert_message = "Invalid number. Cancelled."

            elif node.current_mode == 'DIVIDERS':
                if key in ['1', '2']: node.selected_target = f"divider_{key}"
                elif node.selected_target:
                    # When a real keyboard device is available, _update_divider_jog() drives
                    # the divider off live arrow-key held-state every tick instead - these
                    # keystroke-driven calls are only the fallback for when it isn't.
                    if node.kbd_dev is None and key == ARROW_RIGHT:
                        node.execute_hardware_jog(node.selected_target, 1)
                    elif node.kbd_dev is None and key == ARROW_LEFT:
                        node.execute_hardware_jog(node.selected_target, -1)

                    elif key.upper() == 'A':
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, node.settings)
                        print(f"\r\n[INPUT] Target for {node.selected_target.upper()} (mm) [Enter to Cancel / X for E-Stop]: ", end="")
                        val_str = input().strip().lower()
                        tty.setraw(sys.stdin.fileno())
                        
                        if val_str in ['', 'c']:
                            node.alert_message = "Move cancelled."
                            continue
                        if val_str == 'x':
                            node.sysG.stop_motion()
                            node.current_mode = 'MAIN'
                            node.selected_target = None
                            node.alert_message = "E-STOP TRIGGERED FROM MENU."
                            continue
                            
                        try:
                            val = float(val_str)
                            idx = int(node.selected_target.split('_')[1])
                            node.alert_message = f"Driving {node.selected_target} to {val}mm..."
                            node.desired[node.selected_target] = val
                            node.sysG.move_divider(idx, val)
                        except ValueError:
                            node.alert_message = "Invalid number. Cancelled."

            elif node.current_mode == 'PUSHERS':
                if key.upper() == 'C':
                    node.combined_mode = not node.combined_mode
                    node.selected_target = None
                elif node.combined_mode and key in ['1', '2', '3']:
                    node.selected_target = f"pusher_comb_{key}"
                elif not node.combined_mode and key in ['1', '2', '3', '4']:
                    node.selected_target = f"pusher_{key}"
                elif node.selected_target:
                    # When a real keyboard device is available, _update_pusher_jog() drives
                    # pushers off live arrow-key held-state every tick instead - these
                    # keystroke-driven calls are only the fallback for when it isn't.
                    if node.kbd_dev is None and key == ARROW_DOWN:
                        node.execute_hardware_jog(node.selected_target, 1)
                    elif node.kbd_dev is None and key == ARROW_UP:
                        node.execute_hardware_jog(node.selected_target, -1)

                    elif key.upper() == 'A':
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, node.settings)
                        print(f"\r\n[INPUT] Target for {node.selected_target.upper()} (mm) [Enter to Cancel / X for E-Stop]: ", end="")
                        val_str = input().strip().lower()
                        tty.setraw(sys.stdin.fileno())

                        if val_str in ['', 'c']:
                            node.alert_message = "Move cancelled."
                            continue
                        if val_str == 'x':
                            node.sysG.stop_motion()
                            node.current_mode = 'MAIN'
                            node.selected_target = None
                            node.alert_message = "E-STOP TRIGGERED FROM MENU."
                            continue

                        try:
                            val = float(val_str)
                            if 'comb' in node.selected_target:
                                # Logic for the combined pusher target
                                comb_idx = int(node.selected_target.split('_')[2])
                                idx1 = comb_idx - 1
                                idx2 = comb_idx
                                node.alert_message = f"Driving combined {node.selected_target} to {val}mm..."
                                node.desired[f"pusher_{idx1+1}"] = val
                                node.desired[f"pusher_{idx2+1}"] = val
                                node._move_absolute_combined_rails(idx1, idx2, val)
                            else:
                                # Logic for isolated pusher target
                                idx = int(node.selected_target.split('_')[1])
                                node.alert_message = f"Driving {node.selected_target} to {val}mm..."
                                node.desired[node.selected_target] = val
                                node._move_absolute_isolated_rail(idx - 1, val)
                        except ValueError:
                            node.alert_message = "Invalid number. Cancelled."

            elif node.current_mode == 'SERVOS':
                if key.upper() == 'C':
                    node.combined_mode = not node.combined_mode
                    node.selected_target = None
                elif node.combined_mode and key in ['1', '2', '3']:
                    node.selected_target = f"servo_comb_{key}"
                elif not node.combined_mode and key in ['1', '2', '3', '4']:
                    node.selected_target = f"servo_{key}"
                elif node.selected_target:
                    if key == ARROW_LEFT:  node.execute_hardware_jog(node.selected_target, 1)
                    elif key == ARROW_RIGHT: node.execute_hardware_jog(node.selected_target, -1)

    except KeyboardInterrupt:
        pass
    finally:
        print("\n[SYSTEM] Shutting down. Stopping all hardware")
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, node.settings)
        node.sysG.stop_motion()
        if node.kbd_dev is not None:
            node.kbd_dev.close()

        sys.stdout.write("\033[?25h") # Restoring the Cursor

if __name__ == '__main__':
    main()