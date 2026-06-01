from systemG_arch import SystemG
from time import sleep

if __name__ == "__main__":
    sysG = SystemG()
    sleep(1)
    positions = sysG.get_positions()
    print("Positions:")
    for motor, pos in positions.items():
        for idx, p in enumerate(pos, start=1):
            print(f"  {motor} {idx}: {p} mm")

    # Choose which motors to drive: 
    # rail pairs 1-3: keys 1-3
    # dividers 1-2: keys 4-5
    # doors left & right: keys SHIFT + 4-5
    # servos 1-3: keys SHIFT + 1-3
    motor_map = {
        '1': ('pusher', 1),
        '2': ('pusher', 2),
        '3': ('pusher', 3),
        '4': ('divider', 1),
        '5': ('divider', 2),
        '$': ('door', 1),
        '%': ('door', 2),
        '!': ('servos', 1),
        '@': ('servos', 2),
        '#': ('servos', 3),
        'r': ('jiggle', None),
        'g': ('get', None),
    }

    try:
        while True:
            motor_key = input("Enter motors/servos to drive (1-5) or 'q' to quit: ")
            if motor_key.lower() == 'q':
                break

            if motor_key not in motor_map:
                print("Invalid motor number. Please try again.")
                continue

            motor_type, idx = motor_map[motor_key]

            if motor_type == 'servos':
                direction = input("Enter 'E' to engage, 'D' to disengage %s: " % motor_type).lower()
                if direction not in ['e', 'd']:
                    print("Invalid command. Please try again.")
                    continue
                engage = True if direction == 'e' else False
                print(f"{'Engaging' if engage else 'Disengaging'} partition {idx}.")
                sysG.engage_pushers(idx, engage)
                continue
            
            elif motor_type == 'jiggle':
                sysG.jiggle_motors()
                continue
            elif motor_type == 'get':
                positions = sysG.get_positions()
                print("Positions:")
                for motor, pos in positions.items():
                    for idx, p in enumerate(pos, start=1):
                        print(f"  {motor} {idx}: {p} mm")
                continue

            elif motor_type == 'pusher':
                max_pos = sysG.max_rail_pos
            elif motor_type == 'divider':
                max_pos = sysG.max_div_pos
            elif motor_type == 'door':
                max_pos = sysG.max_door_pos
            pos = input("Enter position to move to (max: %.0fmm): " % max_pos)
            if not pos.isdigit():
                print("Invalid number of steps. Please try again.")
                continue

            pos = int(pos)

            print(f"Moving {motor_type} {idx} to {pos} mm.")
            
            if motor_type == 'pusher':
                sysG.move_pushers(idx, pos)
            elif motor_type == 'divider':
                sysG.move_divider(idx, pos)
            elif motor_type == 'door':
                sysG.move_door(idx, pos)

            print(f"{motor_type.capitalize()} {idx} moved.")

    # Handle keyboard interrupt and stop motion
    except (KeyboardInterrupt, Exception):
        print("\nStopping all motion.")
        sysG.stop_motion()