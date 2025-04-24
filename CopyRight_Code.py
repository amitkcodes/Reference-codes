#Team NPL Amit Kaushik,Divya Singh Yadav,Dr.Deepak Sharma,Dr. Ashish Agrawal,Dr. Subhasis Panja
import socket  # Import the socket library for network communication
import threading  # Import the threading library for concurrent execution
import datetime  # Import the datetime library for date and time operations
import struct  # Import the struct library for packing and unpacking binary data
import time  # Import the time library for time-related functions
import os  # Import the os library for operating system-related tasks
import csv  # Import the csv library for working with CSV files
import requests  # Import the requests library for making HTTP requests
import logging  # Import the logging library for logging messages

# Configure logging to display timestamps, log levels, and messages
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class Config:
    """
    A class to store configuration settings for the NTD synchronization process.
    """
    NTP_SERVER = "192.168.251.32"  # The IP address of the NTP server to synchronize with
    NTD_IPS = {  # A dictionary mapping NTD IP addresses to their locations
        "172.16.26.10": "Testing in Room No. 31",
        "172.16.26.14": "Inside NTDs main_Gate",
        "172.16.26.3": "Outside NTDs main_Gate",
        "172.16.26.9": "Outside head IST",
        "172.16.26.12": "Electrical_section",
        "172.16.26.16": "Reception of auditorium",
        "172.16.26.17": "Inside NTDs auditorium",
        "172.16.26.7": "Conference room metrology"
    }
    #  Dynamically creates log file path relative to script location.
    BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # Get the directory where the current script is located.
    LOG_DIR = os.path.join(BASE_DIR, 'logs')  # Create a 'logs' directory in the same directory as the script.
    LOG_FILE = os.path.join(LOG_DIR, 'NTDs_Display_synchronization_log.csv')  # Synchronization log file path
    ALERT_LOG = os.path.join(LOG_DIR, 'NTDs_SMSAlart_log.csv')  # SMS alert log file path

    BIAS = 0  # Time bias (in seconds) to adjust the NTP time
    SYNC_INTERVAL = 1800  # Synchronization interval in seconds (30 minutes)
    TCP_TIMEOUT = 10  # Timeout for TCP socket connections in seconds

    API_SECRET = "c59a9a09acd020a020f906e33903901446462dec"  # Secret key for the SMS API
    DEVICE_ID = "00000000-0000-0000-b537-d050d47dc40a"  # Device ID for the SMS API
    PHONES = ['+919520010920']  # List of phone numbers to send SMS alerts to
    CHECK_INTERVAL = 3600  # Interval to check synchronization status in seconds (1 hour)
    ALERT_WINDOW = (10, 18)  # Time window (hours) to send SMS alerts (10 AM to 6 PM)


# Track the last synchronization time for each IP address
last_sync_time = {}
# Track the last alert time for each IP address to avoid duplicate alerts
last_alert_time = {}


def get_ntp_time(server):
    """
    Fetches the current time from an NTP server.

    Args:
        server (str): The IP address or hostname of the NTP server.

    Returns:
        float: The NTP time as a Unix timestamp, or None if the time could not be retrieved.
    """
    for attempt in range(3):  # Retry up to 3 times
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Create a UDP socket
        client.settimeout(5)  # Set a timeout of 5 seconds for the socket
        try:
            ntp_packet = b"\x1b" + 47 * b"\0"  # Create an NTP request packet
            client.sendto(ntp_packet, (server, 123))  # Send the NTP request to the server on port 123
            response, _ = client.recvfrom(48)  # Receive the response from the server (48 bytes)
            unpacked = struct.unpack("!12I", response)  # Unpack the response as 12 unsigned integers
            ntp_time = unpacked[10] + unpacked[11] / (2 ** 32)  # Extract the NTP time from the response
            return ntp_time - 2208988800  # Convert NTP time to Unix timestamp (seconds since 1970)
        except Exception as e:
            logging.error(f"Attempt {attempt + 1} failed: {e}")  # Log the error message
            time.sleep(2)  # Wait for 2 seconds before retrying
        finally:
            client.close()  # Close the socket in the finally block to ensure it's always closed
    return None  # Return None if all attempts failed


def create_time_payload(timestamp):
    """
    Creates a time payload in a format compatible with NTD devices.

    Args:
        timestamp (float): The Unix timestamp to be converted into the payload.

    Returns:
        bytes: The time payload as a bytes object.
    """
    ntp_date = datetime.datetime.fromtimestamp(timestamp)  # Convert the timestamp to a datetime object
    return (
        b"\x55\xaa\x00\x00\x01\x01\x00\xc1\x00\x00\x00\x00\x00\x00\x0f\x00\x00\x00\x0f\x00\x10\x00\x00\x00\x00\x00\x00\x00"
        + ntp_date.year.to_bytes(2, "little")  # Convert the year to bytes (2 bytes, little-endian)
        + bytes([ntp_date.month, ntp_date.day, ntp_date.hour,
                 ntp_date.minute, ntp_date.second])  # Convert month, day, hour, minute, second to bytes
        + b"\x00\x00\x0d\x0a"  # Add the trailer bytes
    )


def log_sync_result(ip, status):
    """
    Logs the synchronization result to a CSV file.

    Args:
        ip (str): The IP address of the NTD device.
        status (str): The synchronization status message.
    """
    log_dir = Config.LOG_DIR  # Get the directory of the log file

    # Create the log directory if it doesn't exist
    os.makedirs(log_dir, exist_ok=True)

    local_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')  # Get the current time

    with open(Config.LOG_FILE, "a", newline="") as f:  # Open the log file in append mode
        writer = csv.writer(f)  # Create a CSV writer object
        writer.writerow([  # Write the log entry to the CSV file
            local_time,  # Current time
            ip,  # NTD IP address
            status,  # Synchronization status
            Config.BIAS,  # Time bias
            Config.NTD_IPS.get(ip, "Unknown")  # NTD location
        ])


def sync_ntd(ip, payload):
    """
    Synchronizes a single NTD device with the given time payload.

    Args:
        ip (str): The IP address of the NTD device.
        payload (bytes): The time payload to send to the NTD device.
    """
    location = Config.NTD_IPS.get(ip, "Unknown")  # Get the location of the NTD device
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # Create a TCP socket
            s.settimeout(Config.TCP_TIMEOUT)  # Set the socket timeout
            s.connect((ip, 10000))  # Connect to the NTD device on port 10000
            s.sendall(payload)  # Send the time payload to the NTD device
            response = s.recv(1024)  # Receive the response from the NTD device
            log_sync_result(ip, "Synchronized")  # Log the successful synchronization
            logging.info(f"{location}: Synchronized successful")  # Log the successful synchronization
            last_sync_time[ip] = datetime.datetime.now()  # Update the last synchronization time
    except Exception as e:
        error_msg = f"Not Synchronized: {str(e)}"  # Create an error message
        log_sync_result(ip, error_msg)  # Log the failed synchronization
        logging.error(f"{location}: {error_msg}")  # Log the failed synchronization


def log_alert(timestamp, phone, ip, location, status):
    """Record SMS alert attempts."""
    with open(Config.ALERT_LOG, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, phone, ip, location, status])


def send_alert(ip, location):
    """
    Sends an SMS alert via the smschef API if the device is not synchronized.

    Args:
        ip (str): The IP address of the NTD device.
        location (str): The location of the NTD device.
    """
    current_hour = datetime.datetime.now().hour  # Get the current hour
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Capture timestamp here

    if not (Config.ALERT_WINDOW[0] <= current_hour < Config.ALERT_WINDOW[1]):
        status_message = "Alert suppressed (outside active hours)"  # Log message for outside active hours
        log_alert(timestamp, Config.PHONES[0], ip, location, status_message)  # Log the suppression
        logging.info(f"Alert suppressed for {ip} (outside hours)")
        return

    message = f"Alert! {location} (IP: {ip}) is Not Synchronized."  # Create the SMS message

    for phone in Config.PHONES:  # Iterate through the list of phone numbers
        retries = 1
        while retries > 0:
            try:
                response = requests.post(
                    "https://www.cloud.smschef.com/api/send/sms",
                    params={
                        "secret": Config.API_SECRET,
                        "mode": "devices",
                        "device": Config.DEVICE_ID,
                        "sim": 1,
                        "priority": 1,
                        "phone": phone,
                        "message": message
                    },
                    timeout=10
                )
                result = response.json()
                status_response = result.get('status', 'failed')
                message_response = result.get('message', '').lower()

                # Treat 'queued' or 'success' as successful submission
                if status_response == 'success' or 'queued' in message_response:
                    status_message = "SMS queued for sending" if 'queued' in message_response else "SMS sent successfully"
                    break  # Exit retry loop immediately
                else:
                    status_message = f"SMS failed: {message_response}"
                    retries -= 1
                    time.sleep(2)  # Retry delay

            except Exception as e:
                status_message = f"error: {str(e)}"
                retries -= 1

        log_alert(timestamp, phone, ip, location, status_message)  # Log meaningful status
        logging.info(f"SMS to {phone}: {status_message}")


def check_sync_status():
    """
    Monitor synchronization logs and send deduplicated alerts.
    """
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=1)

    try:
        with open(Config.LOG_FILE, 'r') as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if len(row) < 5:
                    continue

                try:
                    log_time = datetime.datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S.%f')
                    ip = row[1]

                    if log_time > cutoff and "Not Synchronized" in row[2]:
                        location = row[4]

                        # Check last sync and alert times for conditions
                        current_time = datetime.datetime.now()

                        # Check if we've already alerted this IP recently (e.g., within the last hour)
                        if ip in last_alert_time and (
                                current_time - last_alert_time[ip]).total_seconds() < 3600:
                            continue

                        send_alert(ip, location)  # Send alert for unsynchronized IP
                        last_alert_time[ip] = current_time  # Update last alert time

                except ValueError as e:
                    logging.error(f"Invalid timestamp in row {i}: {e}")
                except Exception as e:
                    logging.error(f"Error processing row {i}: {e}")

    except FileNotFoundError:
        logging.error(f"Log file missing: {Config.LOG_FILE}")


def sync_all_and_alert():
    """
    Combines synchronization and alert checks.
    """
    while True:  # Run indefinitely
        logging.info("--- Starting synchronization cycle ---")  # Log the start of the synchronization cycle
        ntp_time = get_ntp_time(Config.NTP_SERVER)  # Get the current time from the NTP server

        if ntp_time:  # If the NTP time was successfully retrieved
            payload = create_time_payload(ntp_time)  # Create the time payload
            for ip in Config.NTD_IPS:  # Iterate through the list of NTD IP addresses
                threading.Thread(target=sync_ntd, args=(ip, payload)).start()  # Start a new thread to synchronize each NTD

        logging.info("Checking synchronization status for alerts...")
        check_sync_status()

        time.sleep(Config.SYNC_INTERVAL)  # Wait for the synchronization interval


if __name__ == "__main__":
    sync_all_and_alert()  # Start the main synchronization and alert loop
