# Gmail Campaign Mailer

A personal, lightweight Python automation script to send ~50 personalized emails per day via Gmail SMTP.

---

## 🛠️ Installation

1. Make sure you have **Python 3.12** (or 3.9+) installed.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## 🔑 1. How to Create a Gmail App Password

Standard passwords do **not** work with Gmail SMTP. You must generate a 16-character App Password.

1. Go to your **Google Account settings** (https://myaccount.google.com/).
2. Enable **2-Step Verification** under Security (if not already enabled).
3. In the search bar at the top, type **"App Passwords"**.
4. Create a new App Password (e.g., name it `Mailer`).
5. Copy the 16-character password generated (e.g., `abcd efgh ijkl mnop`).

---

## ⚙️ 2. Configure Sender Details

Open `mailer.py` in any text editor and edit the configuration block at the top:

```python
SENDER_EMAIL = "your-email@gmail.com"
APP_PASSWORD = "your-16-digit-app-password"
```

---

## 📁 3. Campaign Setup & Customization

### Contacts
Place your contacts in `campaign/contacts.xlsx` (preferred) or `campaign/contacts.csv`.
- The mailer automatically cleans blank emails and removes duplicates.
- Apollo exports work out-of-the-box (`First Name`, `Last Name`, `Company`, `Email` columns are auto-mapped).
- Any extra columns in your file become available as Jinja2 placeholders!

### Subject Line
Edit `campaign/subject.txt`:
```
Hiring Support for {{Company name}}
```

### Email Template
Edit `campaign/template.txt`:
```
Dear {{First name}} {{Last name}},

Hope you are doing well.

We would be happy to support {{Company name}} with your hiring requirements.

Regards,
Ritik Anand
```

### Attachments
Place any files (PDFs, images, docs) into `campaign/attachments/`.
- Every file in this directory will automatically be attached to each outgoing email.

---

## 🚀 4. How to Run

Execute the script by providing the campaign folder as an argument:


1. Create the environment
```bash
python -m venv venv
```
2. Activate it (Command Prompt)
```bash
venv\Scripts\activate.bat
```
OR for PowerShell:
```bash
.\venv\Scripts\Activate.ps1
```
3. Install packages
```bash
pip install -r requirements.txt
```
4. Run
```bash
python mailer.py campaign/
```

1. The script will output contact validation statistics.
2. You will be prompted: `Type 'YES' to proceed with sending:`.
3. Type `YES` and press Enter to begin sending.

---

## 📊 5. Reports

After or during execution, check `campaign/reports/report.csv` to track:
- Recipient email address
- Status (`SUCCESS` or `FAILED`)
- Error reason (if failed)
- Timestamp of dispatch
