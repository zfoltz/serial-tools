import serial
import time
import datetime
import sys

# --- Configuration ---
SERIAL_PORT = 'COM3'
BAUD_RATE = 38400  # Common values: 9600, 115200, 57600
LOG_FILE = 'com3_log.txt'

def log_data():
    try:
        # Open the serial port
        # timeout=1 means the read operation will wait up to 1 second for data
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"[-] Successfully connected to {SERIAL_PORT} at {BAUD_RATE} baud.")
        print(f"[-] Logging to {LOG_FILE}...")
        print("[-] Press Ctrl+C to stop.")

        # Open file in append mode
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            while True:
                try:
                    # Check if there is data waiting in the buffer
                    if ser.in_waiting > 0:
                        # Read all available bytes
                        data_bytes = ser.read(ser.in_waiting)
                        
                        # Get current timestamp
                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        # format data for display/logging
                        # .hex() turns bytes into readable hex (e.g., 00 ff a1)
                        hex_data = data_bytes.hex(' ') 
                        
                        # Attempt to decode as ASCII for readability, replace errors with '.'
                        try:
                            ascii_data = data_bytes.decode('utf-8')
                        except UnicodeDecodeError:
                            ascii_data = str(data_bytes)

                        # Construct the log entry
                        log_entry = f"[{timestamp}] HEX: {hex_data} | ASCII: {ascii_data}"

                        # 1. Print to Console
                        print(log_entry)

                        # 2. Write to File
                        f.write(log_entry + '\n')
                        f.flush()  # Ensure data is written to disk immediately

                    # Sleep briefly to reduce CPU usage
                    time.sleep(0.01)

                except serial.SerialException as e:
                    print(f"[!] Serial error: {e}")
                    break

    except serial.SerialException as e:
        print(f"[!] Could not open {SERIAL_PORT}. Is it in use by another program?")
        print(f"[!] Error details: {e}")
    except KeyboardInterrupt:
        print("\n[-] Stopping logger...")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("[-] Port closed.")

if __name__ == "__main__":
    log_data()