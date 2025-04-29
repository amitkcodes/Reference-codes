import ntplib
import time
import csv
import os
from datetime import datetime
import logging
from flask import Flask, request
import smtplib
from email.mime.text import MIMEText
import pandas as pd
import psycopg2
from threading import Thread

# Configure logging for file and console
logger = logging.getLogger()
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler('ntp_data.log')
console_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# List of NTP servers
ntp_servers = [
    '157.20.66.8', 'ntp.doca.gov.in', 'samay2.nic.in', 'pool.ntp.org',
    '192.168.251.12', '192.168.251.14', '192.168.251.15', '192.168.251.18',
    '192.168.251.21', '192.168.251.22', '192.168.251.24', '192.168.251.30',
    '192.168.251.32', '192.168.251.33', '192.168.251.38', '192.168.251.39'
]

# Directory to save CSV files
output_dir = 'ntp_server_data'
os.makedirs(output_dir, exist_ok=True)

# Initialize NTP client
ntp_client = ntplib.NTPClient()

# Flask app for alerts
app = Flask(__name__)

# Email configuration
EMAIL_ADDRESS = 'amitnplindia21@gmail.com'
EMAIL_PASSWORD = 'ctmweznzewgtypup'  # Update with new app-specific password
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 465

def send_email_alert(subject, body, to_email='amitnplindia21@gmail.com', retries=3, delay=5):
    """Send an email alert with retries in a separate thread."""
    def send():
        for attempt in range(retries):
            try:
                msg = MIMEText(body)
                msg['Subject'] = subject
                msg['From'] = EMAIL_ADDRESS
                msg['To'] = to_email
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
                    server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                    server.send_message(msg)
                logging.info(f"Email alert sent to {to_email}")
                return
            except Exception as e:
                logging.error(f"Attempt {attempt+1}/{retries} failed to send email alert: {str(e)}")
                if attempt < retries - 1:
                    time.sleep(delay)
        logging.error(f"All {retries} attempts to send email to {to_email} failed")
    Thread(target=send, daemon=True).start()

def query_ntp_server(server):
    """Query an NTP server and return offset and delay."""
    for attempt in range(3):
        try:
            response = ntp_client.request(server, timeout=10)
            offset = response.offset
            delay = response.delay
            logging.info(f"Server {server}: Offset={offset:.6f}s, Delay={delay:.6f}s")
            return offset, delay
        except Exception as e:
            logging.warning(f"Attempt {attempt+1}/3 failed for {server}: {str(e)}")
            if attempt < 2:
                time.sleep(2)
    logging.error(f"Failed to query {server}: {str(e)}")
    send_email_alert(
        subject=f"NTP No Response Alert for {server}",
        body=f"Server {server} did not respond: {str(e)}",
        to_email='amitnplindia21@gmail.com'
    )
    return None, None

def calculate_avg_offset(server_data):
    """Calculate the average offset from valid server responses."""
    valid_offsets = [data['offset'] for data in server_data.values() if data['offset'] is not None]
    return sum(valid_offsets) / len(valid_offsets) if valid_offsets else 0

def save_to_csv(server_data, avg_offset):
    """Save data to individual CSV files for each server."""
    logging.info(f"Saving data to CSV for {len(server_data)} servers")
    for server, data in server_data.items():
        if data['offset'] is None or data['delay'] is None:
            logging.warning(f"Skipping CSV write for {server}: No valid data")
            continue
        offset_diff = data['offset'] - avg_offset
        safe_server_name = server.replace('.', '_')
        csv_file = os.path.join(output_dir, f'{safe_server_name}.csv')
        row = {
            'timestamp': data['timestamp'],
            'server': server,
            'offset': data['offset'],
            'delay': data['delay'],
            'offset_diff_from_avg': offset_diff
        }
        file_exists = os.path.isfile(csv_file)
        try:
            with open(csv_file, 'a', newline='') as f:
                fieldnames = ['timestamp', 'server', 'offset', 'delay', 'offset_diff_from_avg']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
            logging.info(f"Wrote data to {csv_file}")
        except Exception as e:
            logging.error(f"Failed to write to {csv_file}: {str(e)}")

def connect_to_db():
    """Connect to PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            dbname="ntp_db",
            user="postgres",
            password="npl@123",
            host="localhost",
            port="5433"
        )
        logging.info("Connected to PostgreSQL database")
        return conn
    except Exception as e:
        logging.error(f"Error connecting to PostgreSQL: {str(e)}")
        return None

def process_csv_directory(csv_dir):
    """Process CSV files and insert data into PostgreSQL."""
    logging.info(f"Processing CSV directory: {csv_dir}")
    conn = connect_to_db()
    if not conn:
        logging.error("No database connection; skipping CSV processing")
        return
    cursor = conn.cursor()
    csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]
    logging.info(f"Found {len(csv_files)} CSV files to process")
    for csv_file in csv_files:
        csv_path = os.path.join(csv_dir, csv_file)
        try:
            df = pd.read_csv(csv_path, parse_dates=['timestamp'])
            logging.info(f"Read {len(df)} rows from {csv_file}")
            for _, row in df.iterrows():
                if row['server'].lower() == 'server' or pd.isna(row['server']):
                    logging.warning(f"Invalid server name in {csv_file}, skipping row")
                    continue
                if pd.isna(row['timestamp']):
                    logging.warning(f"Invalid timestamp in {csv_file}, skipping row")
                    continue
                cursor.execute(
                    """
                    INSERT INTO ntp_data (timestamp, server, "offset", delay, offset_diff_from_avg)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        row['timestamp'],
                        row['server'],
                        row['offset'],
                        row['delay'],
                        row['offset_diff_from_avg']
                    )
                )
            conn.commit()
            logging.info(f"Processed {csv_file}")
        except Exception as e:
            logging.error(f"Error processing {csv_file}: {str(e)}")
    cursor.close()
    conn.close()

def create_table():
    """Create the ntp_data table if it doesn't exist."""
    print("Creating table...")
    try:
        conn = psycopg2.connect(
            dbname="ntp_db",
            user="postgres",
            password="npl@123",
            host="localhost",
            port="5433"
        )
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ntp_data (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP,
                server VARCHAR(50),
                "offset" FLOAT,
                delay FLOAT,
                offset_diff_from_avg FLOAT
            );
        """)
        conn.commit()
        logging.info("Table ntp_data created or already exists")
        print("Table created or exists")
        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error creating table: {str(e)}")
        print(f"Table creation error: {e}")

@app.route('/alert', methods=['POST'])
def trigger_alert():
    """API endpoint to trigger an email alert."""
    data = request.get_json()
    subject = data.get('subject', 'NTP Alert')
    body = data.get('body', 'An NTP issue was detected.')
    to_email = data.get('to_email', 'amitnplindia21@gmail.com')
    send_email_alert(subject, body, to_email)
    return {'status': 'Alert sent'}, 200

def run_flask():
    """Run Flask app in a separate thread."""
    app.run(host='0.0.0.0', port=5000, use_reloader=False)

def main():
    print("Starting main loop...")
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    while True:
        print("Querying NTP servers...")
        server_data = {}
        for server in ntp_servers:
            logging.info(f"Querying server {server}")
            print(f"Querying {server}")
            offset, delay = query_ntp_server(server)
            server_data[server] = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'offset': offset,
                'delay': delay
            }
            if offset is not None and abs(offset) > 0.1:
                send_email_alert(
                    subject=f"NTP Offset Alert for {server}",
                    body=f"Server {server} has high offset: {offset:.6f}s",
                    to_email='amitnplindia21@gmail.com'
                )
        print("Saving to CSV...")
        avg_offset = calculate_avg_offset(server_data)
        save_to_csv(server_data, avg_offset)
        print("Processing CSV directory...")
        process_csv_directory(output_dir)
        print("Sleeping for 600 seconds...")
        time.sleep(60)

if __name__ == '__main__':
    logging.info("Script started")
    try:
        create_table()
        main()
    except KeyboardInterrupt:
        logging.info("Script terminated by user.")
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        print(f"Unexpected error: {e}")