import ntplib
import csv
from datetime import datetime
import time
import logging
import threading


# Logging setup
logging.basicConfig(filename='ntp_data.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Function to query NTP server and print time
def get_offset_and_delay_from_ntp(server):
    ntp_client = ntplib.NTPClient()
    try:
        response = ntp_client.request(server, timeout=10)  # Timeout set to 10 seconds 
        offset_in_sec = response.offset
        delay_in_sec = response.delay
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Format timestamp
        data = {'Time': current_time, 'Server': server, 'Offset': offset_in_sec, 'Delay': delay_in_sec}
        print(f"Current offset and response from server: {server}, Offset: {offset_in_sec}, Delay: {delay_in_sec}, Time: {current_time}")
        save_to_csv(data)  # Save data to CSV file
        logging.info(f"Current offset and response from server: {server}, Offset: {offset_in_sec}, Delay: {delay_in_sec}")
        return offset_in_sec, delay_in_sec
    except ntplib.NTPException as e:
        logging.error(f"Error querying NTP server {server}: {e}")
        return 0, 0
    except Exception as e:
        logging.error(f"Unexpected error querying NTP server {server}: {e}")
        return 0, 0

# Function to save data to CSV file
def save_to_csv(data):
    server = data['Server']
    filename = f'{server}_ntp_data.csv'  # File name based on server name
    try:
        with open(filename, 'a', newline='') as csvfile:
            fieldnames = ['Time', 'Server', 'Offset', 'Delay']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if csvfile.tell() == 0:  # Write header if file is empty
                writer.writeheader()
            # Convert current_time to Unix timestamp (seconds since epoch)
            data['Time'] = datetime.strptime(data['Time'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%dT%H:%M:%SZ')
            writer.writerow(data)
        logging.info(f"Data saved to {filename}")
    except Exception as e:
        logging.error(f"Error saving data to {filename}: {e}")

# Function to fetch data from all servers simultaneously
def fetch_data_from_servers(ntp_servers):
    threads = []
    for server in ntp_servers:
        thread = threading.Thread(target=get_offset_and_delay_from_ntp, args=(server,))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()

# List of NTP servers
ntp_servers = ['time.nplindia.org', 'time.nplindia.in', '14.139.60.103', '14.139.60.106', '14.139.60.107', 'samay1.nic.in', 'samay2.nic.in', 
               '157.20.66.8', 'ntp.doca.gov.in', 
               '192.168.251.12', '192.168.251.13', '192.168.251.14', '192.168.251.15', '192.168.251.16','192.168.251.18', '192.168.251.21', 
               '192.168.251.22', '192.168.251.24', '192.168.251.30', '192.168.251.32', '192.168.251.33', '192.168.251.34', '192.168.251.36', 
               '192.168.251.37', '192.168.251.38', '192.168.251.39']

try:
    while True:
        # Fetch data from all servers simultaneously
        fetch_data_from_servers(ntp_servers)
        
        # Print message before sleeping
        print("Waiting for 5 minutes before collecting data again...")

        # Wait for 5 minutes before collecting data again
        time.sleep(300)  # 5 minutes = 300 seconds

        # Print message after sleeping
        print("Resuming data collection...")
        
except KeyboardInterrupt:
    logging.info("Script interrupted. Exiting gracefully...")
except Exception as e:
    logging.error(f"Unexpected error: {e}")
