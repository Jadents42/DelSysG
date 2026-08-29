import serial

ser = serial.Serial('/dev/serial0', 921600, timeout=0.2)
cts_init = None
ct1 = None
encoders = {}
print("Serial Active")
while True:
    line = ser.readline().decode("ascii", errors="ignore").strip()
    if not line:
        continue

    print(line)

    try:
        key, value = line.split(":")
        encoders[key.strip()] = int(value.strip())

        #print(encoders)

    except ValueError:
        pass
        
    try:
        ct1 = int(encoders['enc1'])
    except ValueError:
        continue
    
    if ct1 is not None:
        if cts_init is None:
            cts_init = ct1
            continue

        # Encoders have 3 counts per revolution
        # Motors are 1/455 gear ratio
        # Resulting in 5,462.22 per revolution
        # Lead screw with 8mm travel per revolution (2mm pitch, 4 starts)
        # Resultin in 682.78 counts per mm travel
        rail_pos = (ct1-cts_init) / 682.78

        print(f"Rail position: {rail_pos:.3f} mm")