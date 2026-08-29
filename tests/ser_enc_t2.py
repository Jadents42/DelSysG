import serial

ser = serial.Serial('/dev/serial0', 921600, timeout = 0.2)
print("Reading Encoders...")

# Encoders have 3 counts per revolution
# Motors are 1/455 gear ratio
# Resulting in 5,462.22 per revolution
# Lead screw with 8mm travel per revolution (2mm pitch, 4 starts)
# Resulting in 682.78 counts per mm travel

rail_pos = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
cts_init = {}
encoders = {}
num_encoders = 6
full_init = False
while True:
    line = ser.readline().decode("ascii", errors="ignore").strip()
    if not line:
        continue

    try:
        print(line)
        key, value = line.split(":")
        num = key.strip()
        ct = int(value.strip())
        encoders[num] = ct

        #print(encoders)
        if not full_init:
            if cts_init.get(num, None) is None:
                cts_init[num] = ct
            else:
                idx = int(num[-1]) - 1
                rail_pos[idx] = (encoders[num]-cts_init[num]) / 682.78
                print(f"rail {idx+1} position: {rail_pos[idx]} mm")
            if len(cts_init) == num_encoders:
                full_init = True
                print("Encoder initialization complete.")
        else:
            idx = int(num[-1]) - 1
            rail_pos[idx] = (encoders[num]-cts_init[num]) / 682.78
            print(f"rail {idx+1} position: {rail_pos[idx]} mm")


    except ValueError:
        pass
    
    # i = 0
    # for num in cts_init.keys():
    #     rail_pos[i] = (encoders[num]-cts_init[num]) / 682.78
    #     print(rail_pos)
    #     i += 1