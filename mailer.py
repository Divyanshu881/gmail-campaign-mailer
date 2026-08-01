"""
Gmail Campaign Mailer
---------------------
A simple, reliable Python script to send personalized bulk emails using Gmail SMTP.
Designed for low-volume outreach (~50 emails/day).
"""

import os
import sys
import time
import csv
import random
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime

from dotenv import load_dotenv
import pandas as pd
from jinja2 import Template

load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")

# Strict check for required credentials
if not SENDER_EMAIL or not APP_PASSWORD:
    raise ValueError("Missing SENDER_EMAIL or APP_PASSWORD in .env file!")

# Keep fallbacks for non-sensitive operational settings
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT   = int(os.getenv("SMTP_PORT", 465))
MIN_DELAY   = int(os.getenv("MIN_DELAY", 30))
MAX_DELAY   = int(os.getenv("MAX_DELAY", 75))
MAX_EMAILS  = int(os.getenv("MAX_EMAILS", 50))

# Default content fallbacks
DEFAULT_SUBJECT = os.getenv("DEFAULT_SUBJECT")
DEFAULT_TEMPLATE = os.getenv("DEFAULT_TEMPLATE")

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def normalize_column_names(df):
    """
    Standardize common column variations to valid Jinja2 variable names (using underscores).
    Maps:
    - First Name / firstname / First_Name -> First_name
    - Last Name / lastname / Last_Name -> Last_name
    - Company / Organization / Company Name -> Company_name
    - Email / Email Address -> Email
    """
    col_mapping = {}
    for col in df.columns:
        clean_col = str(col).strip()
        lower_col = clean_col.lower()
        
        if lower_col in ["first name", "firstname", "first_name"]:
            col_mapping[col] = "First_name"
        elif lower_col in ["last name", "lastname", "last_name"]:
            col_mapping[col] = "Last_name"
        elif lower_col in ["company", "organization", "company name", "company_name"]:
            col_mapping[col] = "Company_name"
        elif lower_col in ["email", "email address", "email_address"]:
            col_mapping[col] = "Email"
        else:
            col_mapping[col] = clean_col  # Keep original name for custom Jinja2 placeholders
            
    df = df.rename(columns=col_mapping)
    return df

def is_valid_email(email):
    """Basic regex validation for email address format."""
    if not isinstance(email, str) or not email.strip():
        return False
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return re.match(pattern, email.strip()) is not None

def load_contacts(campaign_folder):
    """
    Load contacts from contacts.xlsx (preferred) or contacts.csv.
    Normalizes column names, cleans blank/invalid emails, and removes duplicates.
    """
    xlsx_path = os.path.join(campaign_folder, "contacts.xlsx")
    csv_path = os.path.join(campaign_folder, "contacts.csv")
    
    if os.path.exists(xlsx_path):
        print(f"Loading contacts from Excel: {xlsx_path}")
        df = pd.read_excel(xlsx_path)
    elif os.path.exists(csv_path):
        print(f"Loading contacts from CSV: {csv_path}")
        df = pd.read_csv(csv_path)
    else:
        print(f"Error: Neither contacts.xlsx nor contacts.csv found in '{campaign_folder}'.")
        sys.exit(1)
        
    df = normalize_column_names(df)
    
    if "Email" not in df.columns:
        print("Error: Required 'Email' column not found in contact file.")
        sys.exit(1)
        
    # Standardize empty text strings and drop rows where email is blank
    df["Email"] = df["Email"].astype(str).str.strip()
    df = df[df["Email"].notna() & (df["Email"] != "") & (df["Email"] != "nan")]
    
    total_loaded = len(df)
    
    # Filter valid vs invalid emails
    valid_mask = df["Email"].apply(is_valid_email)
    valid_df = df[valid_mask].copy()
    invalid_df = df[~valid_mask].copy()
    
    # Remove duplicate email entries (keep first occurrence)
    valid_df = valid_df.drop_duplicates(subset=["Email"], keep="first")
    
    print(f"--- Contact Summary ---")
    print(f"Total contacts loaded: {total_loaded}")
    print(f"Valid unique emails : {len(valid_df)}")
    print(f"Invalid / empty     : {len(invalid_df)}")
    if len(invalid_df) > 0:
        print("Invalid emails list:", list(invalid_df["Email"]))
    print("------------------------")
    
    return valid_df

def read_template_and_subject(campaign_folder):
    """
    Reads template.txt and subject.txt if available, otherwise falls back to defaults.
    """
    subject_path = os.path.join(campaign_folder, "subject.txt")
    template_path = os.path.join(campaign_folder, "template.txt")
    
    if os.path.exists(subject_path):
        with open(subject_path, "r", encoding="utf-8") as f:
            subject_template = f.read().strip()
        print(f"Loaded subject template from: {subject_path}")
    else:
        subject_template = DEFAULT_SUBJECT
        print("Using default subject template.")
        
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            body_template = f.read().strip()
        print(f"Loaded email body template from: {template_path}")
    else:
        body_template = DEFAULT_TEMPLATE
        print("Using default email body template.")
        
    return subject_template, body_template

def get_attachments(campaign_folder):
    """
    Returns a list of full file paths from campaign/attachments/,
    skipping hidden system files, temp files, and dangerous extensions blocked by Gmail.
    """
    attachments_dir = os.path.join(campaign_folder, "attachments")
    
    # Extensions blocked/flagged by Gmail or common OS temp files
    BLOCKED_EXTENSIONS = {
        # Executables & Installers
        ".exe", ".bat", ".cmd", ".msi", ".msp", ".cpl", ".application", ".gadget",
        # Scripts
        ".vbs", ".js", ".jse", ".jar", ".scr", ".pif", ".hta", ".ps1", ".ps2", ".wsf", ".wsh",
        # Temp / System / Backup
        ".tmp", ".temp", ".bak", ".lnk", ".sys", ".dll"
    }
    
    files = []
    if os.path.exists(attachments_dir):
        for f in os.listdir(attachments_dir):
            # 1. Ignore hidden system files (.DS_Store, .git, etc.)
            if f.startswith(".") or f.startswith("__"):
                continue
                
            file_path = os.path.join(attachments_dir, f)
            
            # 2. Skip directories inside attachments folder
            if not os.path.isfile(file_path):
                continue
                
            # 3. Skip Microsoft Office lock files (e.g., ~$document.docx) or editor backups (ending with ~)
            if f.startswith("~$") or f.endswith("~"):
                print(f"Skipping temp lock file: {f}")
                continue
                
            # 4. Filter out blocked file extensions
            ext = os.path.splitext(f)[1].lower()
            if ext in BLOCKED_EXTENSIONS:
                print(f"Skipping blocked extension file: {f}")
                continue
                
            files.append(file_path)
            
    return files

def build_message(sender, recipient, subject, body, attachment_paths):
    """Constructs a MIME multipart email message with text body and attachments."""
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    
    msg.attach(MIMEText(body, "plain", "utf-8"))
    
    for path in attachment_paths:
        file_name = os.path.basename(path)
        try:
            with open(path, "rb") as f:
                part = MIMEApplication(f.read(), Name=file_name)
            part.add_header("Content-Disposition", "attachment", filename=file_name)
            msg.attach(part)
        except Exception as e:
            print(f"Warning: Failed to attach file {file_name}: {e}")
            
    return msg

def send_email_smtp(msg, sender, app_password):
    """Sends a single email using Gmail SSL SMTP connection."""
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(sender, app_password)
        server.send_message(msg)

# ==============================================================================
# MAIN CAMPAIGN EXECUTION
# ==============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python mailer.py <campaign_folder_path>")
        print("Example: python mailer.py campaign/")
        sys.exit(1)
        
    campaign_folder = sys.argv[1]
    
    if not os.path.exists(campaign_folder):
        print(f"Error: Campaign folder '{campaign_folder}' does not exist.")
        sys.exit(1)
        
    print(f"=== Gmail Campaign Mailer Starting ===")
    print(f"Target Campaign Folder: {campaign_folder}")
    
    # Load inputs
    df_contacts = load_contacts(campaign_folder)
    subject_raw, body_raw = read_template_and_subject(campaign_folder)
    attachment_paths = get_attachments(campaign_folder)
    
    if attachment_paths:
        print(f"Attachments detected ({len(attachment_paths)}):")
        for p in attachment_paths:
            print(f"  - {os.path.basename(p)}")
    else:
        print("No attachments detected in campaign/attachments/")
        
    # Enforce daily limit if needed
    total_to_send = min(len(df_contacts), MAX_EMAILS)
    if len(df_contacts) > MAX_EMAILS:
        print(f"Note: Capping current run to MAX_EMAILS limit of {MAX_EMAILS} (out of {len(df_contacts)} valid contacts).")
        df_contacts = df_contacts.iloc[:MAX_EMAILS]
        
    if total_to_send == 0:
        print("No valid contacts to send to. Exiting.")
        sys.exit(0)
        
    # Confirmation prompt
    print(f"Ready to send {total_to_send} emails using account: {SENDER_EMAIL}")
    confirm = input("Type 'YES' to proceed with sending: ").strip()
    if confirm != "YES":
        print("Campaign aborted by user.")
        sys.exit(0)
        
    # Setup reporting directory and file
    reports_folder = os.path.join(campaign_folder, "reports")
    os.makedirs(reports_folder, exist_ok=True)
    report_csv_path = os.path.join(reports_folder, "report.csv")
    
    # Write header if report doesn't exist
    if not os.path.exists(report_csv_path):
        with open(report_csv_path, "w", newline="", encoding="utf-8") as rf:
            writer = csv.writer(rf)
            writer.writerow(["Email", "Status", "Reason", "Timestamp"])
            
    print("Starting email dispatch loop...")
    
    success_count = 0
    failure_count = 0
    
    jinja_subject = Template(subject_raw)
    jinja_body = Template(body_raw)
    
    for idx, row in df_contacts.iterrows():
        # Convert pandas row to dictionary for Jinja2 template render
        data_dict = {str(k): (str(v) if pd.notna(v) else "") for k, v in row.items()}
        recipient_email = data_dict.get("Email", "").strip()
        
        current_num = success_count + failure_count + 1
        print(f"[{current_num}/{total_to_send}] Processing recipient: {recipient_email}")
        
        # Render template placeholders
        try:
            rendered_subject = jinja_subject.render(**data_dict)
            rendered_body = jinja_body.render(**data_dict)
        except Exception as e:
            err_msg = f"Template rendering error: {e}"
            print(f"  FAILED: {err_msg}")
            failure_count += 1
            with open(report_csv_path, "a", newline="", encoding="utf-8") as rf:
                csv.writer(rf).writerow([recipient_email, "FAILED", err_msg, datetime.now().isoformat()])
            continue
            
        # Prepare MIME message
        msg = build_message(SENDER_EMAIL, recipient_email, rendered_subject, rendered_body, attachment_paths)
        
        # Attempt sending with 1 retry
        sent_success = False
        last_error = ""
        
        for attempt in range(2):
            try:
                send_email_smtp(msg, SENDER_EMAIL, APP_PASSWORD)
                sent_success = True
                break
            except Exception as e:
                last_error = str(e)
                if attempt == 0:
                    print(f"  Attempt 1 failed ({last_error}). Retrying in 5 seconds...")
                    time.sleep(5)
                else:
                    print(f"  Attempt 2 failed ({last_error}). Giving up on this recipient.")
                    
        # Log status and update report
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if sent_success:
            print(f"  SUCCESS: Email sent to {recipient_email}")
            success_count += 1
            with open(report_csv_path, "a", newline="", encoding="utf-8") as rf:
                csv.writer(rf).writerow([recipient_email, "SUCCESS", "", timestamp])
        else:
            print(f"  FAILED: Could not send to {recipient_email}")
            failure_count += 1
            with open(report_csv_path, "a", newline="", encoding="utf-8") as rf:
                csv.writer(rf).writerow([recipient_email, "FAILED", last_error, timestamp])
                
        # Random delay before next email if not the last item
        if current_num < total_to_send:
            delay = random.randint(MIN_DELAY, MAX_DELAY)
            print(f"  Waiting {delay} seconds before sending next email...")
            time.sleep(delay)
            
    # Final Summary
    print("==========================================")
    print("CAMPAIGN COMPLETED SUMMARY")
    print("==========================================")
    print(f"Total Attempted : {total_to_send}")
    print(f"Successful      : {success_count}")
    print(f"Failed          : {failure_count}")
    print(f"Detailed Report : {report_csv_path}")
    print("==========================================")

if __name__ == "__main__":
    main()
