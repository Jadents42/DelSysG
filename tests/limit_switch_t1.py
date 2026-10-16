import serial

# Bench test for the 4 limit switches reported by the STM32.
# Prints the switch states whenever one changes. Press each switch and
# confirm the matching value flips to PRESSED.
# Note: the Blackpill's onboard KEY button is also on A0 (lim4).

PIN_NAMES = ["A6", "A5", "A1", "A0"]

ser = serial.Serial('/dev/serial0', 921600, timeout = 0.2)
print("Reading Limit Switches... (Ctrl+C to stop)")

last = None
while True:
    line = ser.readline().decode("ascii", errors="ignore").strip()
    if not line.startswith("lim:"):
        continue

    states = line.split(":")[1].strip().split(",")
    if len(states) != 4 or states == last:
        continue
    last = states

    print("  ".join(
        f"lim{i+1} ({PIN_NAMES[i]}): {'PRESSED' if s == '1' else 'open   '}"
        for i, s in enumerate(states)
    ))
