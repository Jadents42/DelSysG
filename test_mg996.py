#!/usr/bin/env python3
import time
import sys

print("==================================================")
print("       MARCO: ULTIMATE MG996 SERVO TESTER         ")
print("==================================================")
print(" ⚠️ PRE-FLIGHT HARDWARE CHECKLIST:")
print("  1. 5V/6V Power wired into the GREEN terminal?")
print("  2. Power Supply turned ON (allows at least 2 Amps)?")
print("  3. Servo Plugged into Channel 3?")
print("  4. Wire Colors: BROWN = GND(-), RED = V+, ORANGE = PWM")
print("==================================================\n")

time.sleep(2)

try:
    from adafruit_servokit import ServoKit
except ImportError:
    print("[ERROR] adafruit-circuitpython-servokit library missing!")
    sys.exit(1)

# --- HARDWARE INITIALIZATION ---
print("Attempting to connect to Servo HAT at I2C address 0x40...")
try:
    kit = ServoKit(channels=16, address=0x40)
    print("\n✅ [SUCCESS] Servo HAT detected and initialized!")
except ValueError as e:
    print("\n❌ [FATAL ERROR] Raspberry Pi cannot see the Servo HAT!")
    print(" -> The board is either not seated fully on the pins,")
    print(" -> OR the green terminal block does not have power yet.")
    print(f" -> System error: {e}")
    sys.exit(1)

# --- CONFIGURATION ---
CHANNEL = 0

# MG996 Custom Pulse Range (600-2400 is usually the safest range to get 
# 180 degrees without the gears grinding against the internal metal stops)
try:
    kit.servo[CHANNEL].set_pulse_width_range(600, 2400)
except Exception:
    pass # Failsafe if library version is old

def relax_servo():
    """Cuts the PWM signal so the motor doesn't burn up while sitting still."""
    print(f" -> Relaxing servo on Channel {CHANNEL} (Motor free to spin)")
    kit.servo[CHANNEL].angle = None

def safe_sweep():
    print("\nStarting SAFE Sweep (Press Ctrl+C to abort)...")
    try:
        for _ in range(2):
            print("Angle: 45°")
            kit.servo[CHANNEL].angle = 45
            time.sleep(1.5)
            print("Angle: 90° (Center)")
            kit.servo[CHANNEL].angle = 90
            time.sleep(1.5)
            print("Angle: 135°")
            kit.servo[CHANNEL].angle = 135
            time.sleep(1.5)
        print("Angle: 90° (Center)")
        kit.servo[CHANNEL].angle = 90
    except KeyboardInterrupt:
        pass
    relax_servo()

def full_sweep():
    print("\nStarting FULL Sweep (Press Ctrl+C to abort)...")
    try:
        for _ in range(2):
            print("Angle: 0° (Max Left)")
            kit.servo[CHANNEL].angle = 0
            time.sleep(1.5)
            print("Angle: 90° (Center)")
            kit.servo[CHANNEL].angle = 90
            time.sleep(1.5)
            print("Angle: 180° (Max Right)")
            kit.servo[CHANNEL].angle = 180
            time.sleep(1.5)
        print("Angle: 90° (Center)")
        kit.servo[CHANNEL].angle = 90
    except KeyboardInterrupt:
        pass
    relax_servo()

def manual_angle():
    while True:
        val = input("\nEnter angle (0 to 180) or 'b' to go back: ").strip().lower()
        if val == 'b':
            break
        try:
            ang = float(val)
            if 0 <= ang <= 180:
                print(f"Moving to {ang}°...")
                kit.servo[CHANNEL].angle = ang
            else:
                print("Please enter a number between 0 and 180.")
        except ValueError:
            print("Invalid input.")

# --- MAIN INTERACTIVE MENU ---
try:
    while True:
        print(f"\n==========================================")
        print(f"    SERVO CONTROL MENU (CHANNEL {CHANNEL})")
        print(f"==========================================")
        print(" [1] Safe Sweep (45° -> 90° -> 135°)")
        print(" [2] Full Sweep (0° -> 90° -> 180°)")
        print(" [3] Enter Manual Angle")
        print(" [4] Relax Servo (Turn off motor power)")
        print(" [Q] Quit")
        
        choice = input("\nSelect option: ").strip().upper()
        
        if choice == '1':
            safe_sweep()
        elif choice == '2':
            full_sweep()
        elif choice == '3':
            manual_angle()
        elif choice == '4':
            relax_servo()
        elif choice == 'Q':
            relax_servo()
            print("Exiting tester. Goodbye!")
            break
        else:
            print("Invalid choice. Try again.")

except KeyboardInterrupt:
    relax_servo()
    print("\nExiting tester. Goodbye!")