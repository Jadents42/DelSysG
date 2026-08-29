#!/usr/bin/env python3
import time
import sys
from systemG_arch import SystemG

def run_override_test():
    print("====================================================")
    print("       STM32 STEP FREQUENCY OVERRIDE TEST          ")
    print("====================================================")
    print("Initializing System G...")
    
    try:
        robot = SystemG()
    except Exception as e:
        print(f"Hardware Init Failed: {e}")
        return

    time.sleep(2) # Allow UART thread to establish sync
    
    print(f"\nCurrent Door Positions: {robot.door_pos} mm")
    print("\n--- TEST DESCRIPTION ---")
    print("Instead of sending a massive step burst that causes the motor")
    print("to hum, this script will increment the door position slowly")
    print("to see if the Creality motor can handle a simulated ramp.")
    print("----------------------------------------------------")
    input("Clear the bay area and press Enter to start...")

    # Test settings
    target_distance = 100.0  # mm to travel
    increment_step = 1.0     # mm per step cycle
    delay_between_steps = 0.05 # Delay in seconds (adjust to change speed)

    try:
        # --- GRADUAL FORWARD PASS ---
        print("\n[STEPPING FORWARD] Ramping pulses incrementally...")
        current_target = 0.0
        
        while current_target < target_distance:
            current_target += increment_step
            
            # Send small step increments to mitigate firmware frequency choking
            robot.move_door(1, current_target)
            robot.move_door(2, current_target)
            
            time.sleep(delay_between_steps)
            print(f"Stepping Target to: {current_target:.1f} mm", end="\r")
            
        print(f"\nReached target forward limit. Holding for 2 seconds...")
        time.sleep(2)

        # --- GRADUAL REVERSE PASS ---
        print("\n[STEPPING REVERSE] Returning to home position...")
        while current_target > 0.0:
            current_target -= increment_step
            
            robot.move_door(1, current_target)
            robot.move_door(2, current_target)
            
            time.sleep(delay_between_steps)
            print(f"Stepping Target to: {current_target:.1f} mm", end="\r")

        print("\n\n====================================================")
        print("Test cycle finished!")
        print("====================================================")

    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
    finally:
        robot.stop_motion()
        print("System safely stopped.")

if __name__ == "__main__":
    run_override_test()