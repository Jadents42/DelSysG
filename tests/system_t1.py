from system_arch import SystemG
from time import sleep

sys = SystemG()
sleep(1)

def test_system_t1():

    # MOVE DIVIDERS TO CREATE PARTITIONS
    # print("TESTING DIVIDERS")
    # print(f"Divider positions: {sys.div_pos}")

    # idx = 2
    # dist = 400 # mm
    # print(f"Moving divider {idx} to {dist} mm")
    # sys.move_divider(idx, dist)
    # sleep(1)

    # idx = 1
    # dist = 200
    # print(f"Moving divider {idx} to {dist} mm")
    # sys.move_divider(idx, dist)
    # sleep(1)

    # print(f"Divider positions: {sys.div_pos}")
    
    # TEST PARTITION 1
    print("TESTING PARTITION 1")
    print(f"Rail positions: {sys.rail_pos}")

    idx = 1
    engage = True
    print(f"Engaging partition {idx} pushers")
    sys.engage_pushers(idx, engage)
    sleep(1)

    dist = 100
    print(f"Moving partition {idx} pushers to {dist} mm")
    sys.move_pushers(idx, dist)
    sleep(1)

    engage = False
    print(f"Disengaging partition {idx} pushers")
    sys.engage_pushers(idx, engage)
    sleep(1)

    print(f"Rail positions: {sys.rail_pos}")

    # TEST PARTITION 2
    print("TESTING PARTITION 2")
    print(f"Rail positions: {sys.rail_pos}")

    idx = 2
    engage = True
    print(f"Engaging partition {idx} pushers")
    sys.engage_pushers(idx, engage)
    sleep(1)

    dist = sys.RAIL_LEFT_ENDSTOP
    print(f"Moving partition {idx} pushers to {dist} mm")
    sys.move_pushers(idx, dist)
    sleep(1)

    engage = False
    print(f"Disengaging partition {idx} pushers")
    sys.engage_pushers(idx, engage)
    sleep(1)

    print(f"Rail positions: {sys.rail_pos}")

    # TEST PARTITION 3
    print("TESTING PARTITION 3")
    print(f"Rail positions: {sys.rail_pos}")
    
    idx = 3
    engage = True
    print(f"Engaging partition {idx} pushers")
    sys.engage_pushers(idx, engage)
    sleep(1)

    dist = sys.RAIL_RIGHT_ENDSTOP
    print(f"Moving partition {idx} pushers to {dist} mm")
    sys.move_pushers(idx, dist)
    sleep(1)

    engage = False
    print(f"Disengaging partition {idx} pushers")
    sys.engage_pushers(idx, engage)
    sleep(1)

    print(f"Rail positions: {sys.rail_pos}")

    # TEST DOORS
    # print("TESTING DOORS")
    # print(f"Door positions: {sys.door_pos}")

    # side = 0
    # height = 100
    # print(f"Opening left door to {height} mm")
    # sys.move_doors(side, height)
    # sleep(1)

    # side = 1
    # height = 200
    # print(f"Opening right door to {height} mm")
    # sys.move_doors(side, height)
    # sleep(1)

    # print(f"Door positions: {sys.door_pos}")


    print("TEST COMPLETE")



if __name__ == "__main__":
    print("Initializing system for TEST T1")

    set_pos = input("Set initial positions? (y/n): ")

    if set_pos.lower() == 'y':
        div1 = input("Enter initial divider 1 position: ")
        div2 = input("Enter initial divider 2 position: ")
        sys.set_positions(group = "dividers", positions = [int(div1), int(div2)])

        r1 = input("Enter initial rail 1 position: ")
        r2 = input("Enter initial rail 2 position: ")
        r3 = input("Enter initial rail 3 position: ")
        r4 = input("Enter initial rail 4 position: ")
        sys.set_positions(group = "rails", positions = [int(r1), int(r2), int(r3), int(r4)])
    else:
        print("Using default initial positions (0)")

    test_system_t1()