import serial

# Initialize serial communication
ser = serial.Serial('/dev/serial0', 921600, timeout=.2)

# Take user input
num1 = int(input("Door 1 or 2: "))
if num1 not in [1, 2]:
    print("Invalid input. Please enter 1 or 2.")
    exit()

num2 = int(input("Enter any step value: "))

# Format and send the message
message = f"step{num1}: {num2}"
ser.write(message.encode())

print(f"Message sent: {message}")
ser.close()