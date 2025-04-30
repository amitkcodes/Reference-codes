# Copyright (c) 2025 Amit Kaushik
# Idea by: Divya Singh Yadav
# Code written by: Amit Kaushik
# All rights reserved.
#
# -------------------------------------Preserved Functionality:------------------------------------
# Consecutive Checks: The script tracks failures and deviations across monitoring cycles (every 5 minutes).
# If a server fails 3 times in a row (15 minutes) or has high deviations 3 times in a row, an alert is sent.
# Reset Logic: Counts reset after an alert or when the condition is not met
# (e.g., successful query or deviation ≤ 0.01 seconds), preventing false positives.
# - Alerting after 3 consecutive no-response failures.
# - Alerting after 3 consecutive deviations > 0.01 seconds (10 ms).
# - Alerts for abs(offset_in_sec) > 0.5 or delay_in_sec > 0.2 (immediate, no consecutive check).
# - Rate-limiting (1 alert/hour/server).
# - Log rotation (10 MB, 5 backups).
# - Data saving to PostgreSQL database (replacing CSV).
# - Thread pool with 4 workers.
# - 5-minute monitoring interval.
#
# -------------------------------------Change Log:------------------------------------
# 2025-04-30: Changed column name from 'offset' to 'ntp_offset' in ntp_data table
# (init_db, get_offset_and_delay_from_ntp, save_to_postgres, fetch_data_from_servers)
# to avoid syntax errors, as 'offset' is a reserved keyword in PostgreSQL.

#---------------------------------------Import Section-------------------------------------
import threading  # For running NTP monitoring in a separate thread
from flask import Flask, request  # For creating a web API to send alerts
import smtplib  # For sending emails via Gmail SMTP
from email.mime.text import MIMEText  # For formatting email messages
import ntplib  # For querying NTP servers
from datetime import datetime  # For handling timestamps
import time  # For handling delays and rate-limiting
import logging  # For logging events to a file
from logging.handlers import RotatingFileHandler  # For rotating log files
from concurrent.futures import ThreadPoolExecutor  # For concurrent NTP queries
import requests  # For sending HTTP requests to the Flask API
import json  # For handling JSON data
import os  # For handling file paths
import psycopg2  # For PostgreSQL database connection
from psycopg2.extras import RealDictCursor  # For dictionary-like cursor

# Initialize Flask app for handling API requests
app = Flask(__name__)

# Gmail credentials for sending email alerts
EMAIL = "amitnplindia21@gmail.com"
PASSWORD = "ctmweznzewgtypup"  # App-specific password for Gmail SMTP

# PostgreSQL database configuration
DB_CONFIG = {
    'dbname': 'ntp_database',
    'user': 'postgres',
    'password': 'npl@123',
    'host': 'localhost',
    'port': '5433'
}

# Dictionary to track the last alert time for each server (for rate-limiting)
last_alert_time = {}

# Dictionaries to track consecutive failures and deviations for each server
consecutive_failures = {}  # Tracks consecutive no-response counts
consecutive_deviations = {}  # Tracks consecutive high deviation counts

# --------------------------------------------Flask endpoint to handle POST requests for sending email alerts-----------------------------------
@app.route('/send-sms', methods=['POST'])
def send_sms():
    raw_data = request.get_data(as_text=True)
    print("Raw data received:", raw_data)
    
    data = request.json
    message = data.get('message')
    to_emails = data.get('to_emails')

    if not isinstance(to_emails, list):
        return {"status": "Error: 'to_emails' must be a list"}, 400

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL, PASSWORD)
            for email in to_emails:
                msg = MIMEText(message)
                msg['Subject'] = 'SMS Alert'
                msg['From'] = EMAIL
                msg['To'] = email
                server.send_message(msg)
        return {"status": f"Email sent to {len(to_emails)} recipients"}
    except Exception as e:
        return {"status": f"Failed to send email: {str(e)}"}, 500

# -----------------------------------------Setup logging with rotation to manage log file size--------------------------------------
log_file = os.path.join(os.getcwd(), 'ntp_data.log')
handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
logging.basicConfig(handlers=[handler], level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# -----------------------------------------Function to send alerts via Flask API with rate-limiting----------------------------------
def send_alert(message, to_emails):
    server = message.split("Server: ")[1].split("\n")[0] if "Server: " in message else "unknown"
    current_time = time.time()
    
    if server not in last_alert_time or current_time - last_alert_time[server] > 3600:
        last_alert_time[server] = current_time
        url = 'http://127.0.0.1:5000/send-sms'
        payload = {'message': message, 'to_emails': to_emails}
        headers = {'Content-Type': 'application/json'}
        try:
            response = requests.post(url, data=json.dumps(payload), headers=headers)
            response.raise_for_status()
            logging.info(f"Alert sent: {response.json()}")
        except requests.RequestException as e:
            logging.error(f"Failed to send alert: {e}")

# -----------------------------------------Function to initialize PostgreSQL table--------------------------------------
def init_db():
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        # Create table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ntp_data (
                id SERIAL PRIMARY KEY,
                time TIMESTAMP NOT NULL,
                server VARCHAR(255) NOT NULL,
                ntp_offset FLOAT NOT NULL,
                delay FLOAT NOT NULL,
                offset_diff_from_avg FLOAT NOT NULL,
                sign VARCHAR(10) NOT NULL
            )
        """)
        conn.commit()
        logging.info("PostgreSQL table initialized successfully")
    except Exception as e:
        logging.error(f"Error initializing PostgreSQL table: {e}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

# ----------------------------------------------Function to query an NTP server for offset and delay--------------------------------------
def get_offset_and_delay_from_ntp(server, alert_emails):
    try:
        ntp_client = ntplib.NTPClient()
        response = ntp_client.request(server, timeout=10)
        offset_in_sec = response.offset
        delay_in_sec = response.delay
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        consecutive_failures[server] = 0
        
        data = {
            'time': current_time,
            'server': server,
            'ntp_offset': offset_in_sec,
            'delay': delay_in_sec,
            'offset_diff_from_avg': 0,
            'sign': ''
        }
        
        print(f"Current offset and response from server: {server}, Offset: {offset_in_sec}, Delay: {delay_in_sec}, Time: {current_time}")
        logging.info(f"Current offset and response from server: {server}, Offset: {offset_in_sec}, Delay: {delay_in_sec}")
        
        if delay_in_sec < 0:
            logging.warning(f"Negative delay detected for {server}: {delay_in_sec}")
        elif abs(offset_in_sec) > 0.5 or delay_in_sec > 0.2:
            alert_message = (
                f"NTP Server Alert\n"
                f"Server: {server}\n"
                f"Offset: {offset_in_sec:.6f} seconds\n"
                f"Delay: {delay_in_sec:.6f} seconds\n"
                f"Time: {current_time}"
            )
            send_alert(alert_message, alert_emails)
        
        return offset_in_sec, delay_in_sec, data
    except (ntplib.NTPException, Exception) as e:
        logging.error(f"Error querying NTP server {server}: {e}")
        print(f"Error querying NTP server {server}: {e}")
        
        consecutive_failures[server] = consecutive_failures.get(server, 0) + 1
        
        if consecutive_failures[server] >= 3:
            alert_message = (
                f"NTP Server No Response Alert\n"
                f"Server: {server}\n"
                f"Error: Failed to respond 3 consecutive times\n"
                f"Last Error: {str(e)}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            send_alert(alert_message, alert_emails)
            consecutive_failures[server] = 0
        
        data = {
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'server': server,
            'ntp_offset': 0,
            'delay': 0,
            'offset_diff_from_avg': 0,
            'sign': ''
        }
        return 0, 0, data

# ----------------------------------------------Function to save NTP data to PostgreSQL--------------------------------------------
def save_to_postgres(data):
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        # Insert data into ntp_data table
        cursor.execute("""
            INSERT INTO ntp_data (time, server, ntp_offset, delay, offset_diff_from_avg, sign)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            datetime.strptime(data['time'], '%Y-%m-%d %H:%M:%S'),
            data['server'],
            data['ntp_offset'],
            data['delay'],
            data['offset_diff_from_avg'],
            data['sign']
        ))
        conn.commit()
        logging.info(f"Data saved to PostgreSQL for server: {data['server']}, time: {data['time']}")
    except Exception as e:
        logging.error(f"Error saving data to PostgreSQL: {e}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

# ----------------------------------------------Function to fetch data from all NTP servers concurrently--------------------------------
def fetch_data_from_servers(ntp_servers, alert_emails):
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(get_offset_and_delay_from_ntp, server, alert_emails) for server in ntp_servers]
        for future in futures:
            results.append((None, future.result()))
    
    valid_offsets = [(offset, data) for _, (offset, _, data) in results if offset != 0]
    if valid_offsets:
        offsets = [offset for offset, _ in valid_offsets]
        avg_offset = sum(offsets) / len(offsets)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"Average offset across {len(valid_offsets)} servers: {avg_offset:.6f} seconds, Time: {current_time}")
        logging.info(f"Average offset across {len(valid_offsets)} servers: {avg_offset:.6f} seconds")
        
        for _, (offset, delay, data) in results:
            if offset != 0:
                diff = offset - avg_offset
                sign = '+' if diff >= 0 else '-'
                data['offset_diff_from_avg'] = diff
                data['sign'] = sign
                print(f"Server: {data['server']}, Offset Diff from Avg: {diff:.6f}, Sign: {sign}")
                logging.info(f"Server: {data['server']}, Offset Diff from Avg: {diff:.6f}, Sign: {sign}")
                
                if abs(diff) > 0.01:
                    consecutive_deviations[server] = consecutive_deviations.get(server, 0) + 1
                    if consecutive_deviations[server] >= 3:
                        alert_message = (
                            f"NTP Server Offset Deviation Alert\n"
                            f"Server: {data['server']}\n"
                            f"Offset: {offset:.6f} seconds\n"
                            f"Delay: {delay:.6f} seconds\n"
                            f"Offset Diff from Avg: {diff:.6f} seconds\n"
                            f"Sign: {sign}\n"
                            f"Time: {current_time}\n"
                            f"Consecutive Deviations: {consecutive_deviations[server]}"
                        )
                        send_alert(alert_message, alert_emails)
                        consecutive_deviations[server] = 0
                else:
                    consecutive_deviations[server] = 0
            save_to_postgres(data)
        
        # Save average data to PostgreSQL
        avg_data = {
            'time': current_time,
            'server': 'Average',
            'ntp_offset': avg_offset,
            'delay': 0,
            'offset_diff_from_avg': 0,
            'sign': 'N/A'
        }
        save_to_postgres(avg_data)
    else:
        for _, (_, _, data) in results:
            save_to_postgres(data)
        print("No valid offsets to calculate average.")
        logging.info("No valid offsets to calculate average.")

# -------------------------------------------------Function to run continuous NTP monitoring---------------------------------------------
def run_ntp_monitoring(ntp_servers, alert_emails):
    try:
        while True:
            fetch_data_from_servers(ntp_servers, alert_emails)
            print("Waiting for 5 minutes before collecting data again...")
            time.sleep(300)
            print("Resuming data collection...")
    except KeyboardInterrupt:
        logging.info("Script interrupted. Exiting gracefully...")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")

# ---------------------------------------------------------Main execution block------------------------------------------------------
if __name__ == '__main__':
    # List of NTP servers to monitor
    ntp_servers = [
        '157.20.66.8', 'ntp.doca.gov.in', 'samay1.nic.in', 'samay2.nic.in',
        '192.168.251.12', '192.168.251.14', '192.168.251.15', '192.168.251.18',
        '192.168.251.21', '192.168.251.22', '192.168.251.24', '192.168.251.30',
        '192.168.251.32', '192.168.251.33', '192.168.251.38', '192.168.251.39'
    ]
    
    # List of email addresses for alerts
    alert_emails = ['amitnplindia21@gmail.com']
    
    # Initialize PostgreSQL table
    init_db()
    
    # Initialize failure and deviation counters for each server
    for server in ntp_servers:
        consecutive_failures[server] = 0
        consecutive_deviations[server] = 0
    
    # Start NTP monitoring in a separate thread
    ntp_thread = threading.Thread(target=run_ntp_monitoring, args=(ntp_servers, alert_emails))
    ntp_thread.daemon = True
    ntp_thread.start()
    
    # Run Flask app to handle alert requests
    app.run(debug=True, use_reloader=False, host='127.0.0.1', port=5000)