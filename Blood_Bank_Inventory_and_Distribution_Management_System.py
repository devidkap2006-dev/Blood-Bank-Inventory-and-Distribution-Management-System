from flask import Flask, request, redirect, url_for, session, flash, send_file, render_template_string
import mysql.connector
from mysql.connector import Error
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import date, datetime, timedelta
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = "change-this-blood-bank-secret-key"


DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "932512",
    "database": "blood_bank_management"
}


# -------------------- DATABASE --------------------

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def initialize_database():
    config = DB_CONFIG.copy()
    config.pop("database")

    con = mysql.connector.connect(**config)
    cur = con.cursor()
    cur.execute("CREATE DATABASE IF NOT EXISTS blood_bank_management")
    cur.close()
    con.close()

    con = get_connection()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'Admin'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS donors (
            id INT AUTO_INCREMENT PRIMARY KEY,
            donor_name VARCHAR(120) NOT NULL,
            age INT NOT NULL,
            gender VARCHAR(30),
            blood_group VARCHAR(5) NOT NULL,
            phone VARCHAR(30),
            email VARCHAR(120),
            address TEXT,
            last_donation_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS hospitals (
            id INT AUTO_INCREMENT PRIMARY KEY,
            hospital_name VARCHAR(150) NOT NULL,
            contact_person VARCHAR(120),
            phone VARCHAR(30),
            email VARCHAR(120),
            address TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS donations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            donor_id INT NOT NULL,
            donation_date DATE NOT NULL,
            blood_group VARCHAR(5) NOT NULL,
            quantity_ml INT NOT NULL DEFAULT 450,
            screening_status VARCHAR(30) DEFAULT 'Pending',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (donor_id) REFERENCES donors(id)
                ON DELETE RESTRICT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS blood_units (
            id INT AUTO_INCREMENT PRIMARY KEY,
            donation_id INT,
            blood_group VARCHAR(5) NOT NULL,
            component VARCHAR(50) DEFAULT 'Whole Blood',
            quantity_ml INT NOT NULL DEFAULT 450,
            collection_date DATE NOT NULL,
            expiry_date DATE NOT NULL,
            status VARCHAR(30) DEFAULT 'Available',
            FOREIGN KEY (donation_id) REFERENCES donations(id)
                ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS blood_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            hospital_id INT,
            patient_reference VARCHAR(100),
            blood_group VARCHAR(5) NOT NULL,
            component VARCHAR(50) DEFAULT 'Whole Blood',
            units_required INT NOT NULL,
            request_date DATE NOT NULL,
            required_by DATE,
            urgency VARCHAR(30) DEFAULT 'Normal',
            status VARCHAR(30) DEFAULT 'Pending',
            notes TEXT,
            FOREIGN KEY (hospital_id) REFERENCES hospitals(id)
                ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS distributions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            request_id INT NOT NULL,
            blood_unit_id INT NOT NULL,
            hospital_id INT,
            issue_date DATE NOT NULL,
            issued_by VARCHAR(100),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (request_id) REFERENCES blood_requests(id)
                ON DELETE RESTRICT,
            FOREIGN KEY (blood_unit_id) REFERENCES blood_units(id)
                ON DELETE RESTRICT,
            FOREIGN KEY (hospital_id) REFERENCES hospitals(id)
                ON DELETE SET NULL,
            UNIQUE KEY unique_issued_unit (blood_unit_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            category VARCHAR(100),
            description TEXT,
            amount DECIMAL(12,2) DEFAULT 0,
            expense_date DATE NOT NULL
        )
    """)

    cur.execute("SELECT id FROM users WHERE username='admin'")
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users(username,password,role) VALUES(%s,%s,%s)",
            ("admin", "admin123", "Admin")
        )

    con.commit()
    cur.close()
    con.close()


def run_query(sql, values=(), fetch=False):
    con = get_connection()
    cur = con.cursor(dictionary=True)
    try:
        cur.execute(sql, values)
        result = cur.fetchall() if fetch else cur.lastrowid
        con.commit()
        return result
    finally:
        cur.close()
        con.close()


def refresh_expired_units():
    # Expired units are automatically removed from available stock.
    run_query("""
        UPDATE blood_units
        SET status='Expired'
        WHERE status='Available' AND expiry_date < %s
    """, (date.today(),))


# -------------------- AUTHENTICATION --------------------

def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


# -------------------- COMMON HTML --------------------

BASE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blood Bank Inventory & Distribution</title>
<style>
*{box-sizing:border-box}
body{font-family:Arial,sans-serif;background:#f4f5f7;margin:0;color:#263238}
header{background:#8b1e2d;color:white;padding:19px 25px}
header a{color:white;float:right}
nav{background:#641824;padding:14px 20px;display:flex;flex-wrap:wrap;gap:16px}
nav a{color:white;text-decoration:none;font-size:14px}
main{max-width:1250px;margin:25px auto;padding:0 18px}
.card{background:white;padding:20px;margin:16px 0;border-radius:9px;box-shadow:0 2px 9px #00000012}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:15px}
.stat{background:white;padding:20px;border-radius:9px;box-shadow:0 2px 9px #00000012}
.stat strong{display:block;font-size:27px;color:#a52235;margin-top:8px}
input,select,textarea{padding:10px;margin:5px 4px 5px 0;border:1px solid #cbd0d5;border-radius:5px;max-width:100%}
textarea{width:280px;height:65px;vertical-align:top}
button,.btn{background:#a52235;color:white;border:0;padding:10px 15px;border-radius:5px;cursor:pointer;text-decoration:none;display:inline-block}
table{width:100%;border-collapse:collapse;background:white}
th,td{padding:11px;border-bottom:1px solid #e3e3e3;text-align:left;font-size:14px}
th{background:#f7e8eb}
.notice{background:#fff1cf;padding:12px;margin:10px 0;border-radius:5px}
.muted{color:#68727c;font-size:13px}
.login{max-width:420px;margin:75px auto}
.warning{background:#fff3cd;border-left:4px solid #d39e00;padding:12px}
@media(max-width:650px){nav{gap:9px}table{display:block;overflow-x:auto}}
</style>
</head>
<body>
<header>
<b>BLOOD BANK INVENTORY & DISTRIBUTION MANAGEMENT SYSTEM</b>
{% if session.get('user_id') %}
<a href="/logout">Logout ({{session.get('username')}})</a>
{% endif %}
</header>
{% if session.get('user_id') %}
<nav>
<a href="/dashboard">Dashboard</a>
<a href="/donors">Donors</a>
<a href="/hospitals">Hospitals</a>
<a href="/donations">Donations</a>
<a href="/inventory">Blood Inventory</a>
<a href="/requests">Blood Requests</a>
<a href="/distribution">Distribution</a>
<a href="/expenses">Expenses</a>
<a href="/analytics">Analytics</a>
<a href="/reports">Reports</a>
</nav>
{% endif %}
<main>
{% for msg in get_flashed_messages() %}
<div class="notice">{{msg}}</div>
{% endfor %}
{{content|safe}}
</main>
</body>
</html>
"""


def page(html, **data):
    content = render_template_string(html, **data)
    return render_template_string(BASE, content=content)


def make_table(rows):
    if not rows:
        return "<p class='muted'>No records found.</p>"
    html = "<div style='overflow-x:auto'><table><tr>"
    for key in rows[0]:
        html += f"<th>{key.replace('_', ' ').title()}</th>"
    html += "</tr>"
    for row in rows:
        html += "<tr>"
        for value in row.values():
            html += f"<td>{value if value is not None else ''}</td>"
        html += "</tr>"
    return html + "</table></div>"


BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
COMPONENTS = ["Whole Blood", "Packed Red Cells", "Platelets", "Plasma"]


# -------------------- LOGIN --------------------

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        users = run_query(
            "SELECT * FROM users WHERE username=%s AND password=%s",
            (username, password), fetch=True
        )
        if users:
            session["user_id"] = users[0]["id"]
            session["username"] = users[0]["username"]
            session["role"] = users[0]["role"]
            return redirect("/dashboard")
        flash("Invalid username or password.")

    return page("""
    <div class="card login">
    <h2>Blood Bank Admin Login</h2>
    <form method="post">
    <p><input name="username" placeholder="Username" required style="width:100%"></p>
    <p><input name="password" type="password" placeholder="Password" required style="width:100%"></p>
    <button style="width:100%">Login</button>
    </form>
    <p class="muted">First-time login: admin / admin123</p>
    </div>
    """)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# -------------------- DASHBOARD --------------------

@app.route("/dashboard")
@login_required
def dashboard():
    refresh_expired_units()
    donors = run_query("SELECT COUNT(*) AS n FROM donors", fetch=True)[0]["n"]
    hospitals = run_query("SELECT COUNT(*) AS n FROM hospitals", fetch=True)[0]["n"]
    available = run_query(
        "SELECT COUNT(*) AS n FROM blood_units WHERE status='Available'",
        fetch=True
    )[0]["n"]
    pending = run_query(
        "SELECT COUNT(*) AS n FROM blood_requests WHERE status='Pending'",
        fetch=True
    )[0]["n"]
    return page("""
    <h2>Dashboard</h2>
    <div class="grid">
    <div class="stat">Registered Donors<strong>{{donors}}</strong></div>
    <div class="stat">Hospitals<strong>{{hospitals}}</strong></div>
    <div class="stat">Available Blood Units<strong>{{available}}</strong></div>
    <div class="stat">Pending Requests<strong>{{pending}}</strong></div>
    </div>
    <div class="card">
    <h3>Welcome to Blood Bank Management</h3>
    Manage donor records, donations, blood stock, hospital requests and distribution records.
    <p class="warning">This application is an academic inventory-management demo. Actual donor eligibility,
    infectious-disease screening, compatibility testing, crossmatching, storage conditions and release
    decisions must be handled under applicable blood-bank regulations by qualified professionals.</p>
    </div>
    """, donors=donors, hospitals=hospitals, available=available, pending=pending)


# -------------------- DONORS --------------------

@app.route("/donors", methods=["GET", "POST"])
@login_required
def donors():
    if request.method == "POST":
        age = int(request.form["age"])
        if age < 18 or age > 100:
            flash("Please enter an age from 18 to 100 for this demo record.")
            return redirect("/donors")
        run_query("""
            INSERT INTO donors
            (donor_name,age,gender,blood_group,phone,email,address,last_donation_date)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            request.form["donor_name"], age, request.form["gender"],
            request.form["blood_group"], request.form["phone"],
            request.form["email"], request.form["address"],
            request.form.get("last_donation_date") or None
        ))
        flash("Donor record added.")
        return redirect("/donors")

    rows = run_query("""
        SELECT id,donor_name,age,gender,blood_group,phone,email,address,last_donation_date
        FROM donors ORDER BY id DESC
    """, fetch=True)

    return page("""
    <h2>Donor Management</h2>
    <div class="card"><h3>Register Donor</h3>
    <form method="post">
    <input name="donor_name" placeholder="Donor full name" required>
    <input name="age" type="number" min="18" max="100" placeholder="Age" required>
    <select name="gender"><option>Male</option><option>Female</option><option>Other</option><option>Prefer not to say</option></select>
    <select name="blood_group" required>{% for g in groups %}<option>{{g}}</option>{% endfor %}</select>
    <input name="phone" placeholder="Phone number">
    <input name="email" type="email" placeholder="Email">
    <input name="address" placeholder="Address">
    <label>Last donation <input name="last_donation_date" type="date"></label>
    <button>Save Donor</button>
    </form></div>
    <div class="card"><h3>Donor Records</h3>{{table|safe}}</div>
    """, groups=BLOOD_GROUPS, table=make_table(rows))


# -------------------- HOSPITALS --------------------

@app.route("/hospitals", methods=["GET", "POST"])
@login_required
def hospitals():
    if request.method == "POST":
        run_query("""
            INSERT INTO hospitals(hospital_name,contact_person,phone,email,address)
            VALUES(%s,%s,%s,%s,%s)
        """, (
            request.form["hospital_name"], request.form["contact_person"],
            request.form["phone"], request.form["email"], request.form["address"]
        ))
        flash("Hospital record added.")
        return redirect("/hospitals")

    rows = run_query("SELECT * FROM hospitals ORDER BY id DESC", fetch=True)
    return page("""
    <h2>Hospital Management</h2>
    <div class="card"><h3>Register Hospital</h3><form method="post">
    <input name="hospital_name" placeholder="Hospital name" required>
    <input name="contact_person" placeholder="Contact person">
    <input name="phone" placeholder="Phone">
    <input name="email" type="email" placeholder="Email">
    <input name="address" placeholder="Address">
    <button>Add Hospital</button>
    </form></div>
    <div class="card"><h3>Hospital Records</h3>{{table|safe}}</div>
    """, table=make_table(rows))


# -------------------- DONATION RECORDS --------------------

@app.route("/donations", methods=["GET", "POST"])
@login_required
def donations():
    donors_list = run_query(
        "SELECT id,donor_name,blood_group FROM donors ORDER BY donor_name",
        fetch=True
    )

    if request.method == "POST":
        donor = run_query(
            "SELECT id,blood_group FROM donors WHERE id=%s",
            (request.form["donor_id"],), fetch=True
        )
        if not donor:
            flash("Select a valid donor.")
            return redirect("/donations")

        donation_date = request.form["donation_date"]
        run_query("""
            INSERT INTO donations
            (donor_id,donation_date,blood_group,quantity_ml,screening_status,notes)
            VALUES(%s,%s,%s,%s,%s,%s)
        """, (
            request.form["donor_id"], donation_date,
            donor[0]["blood_group"], int(request.form["quantity_ml"]),
            request.form["screening_status"], request.form["notes"]
        ))
        run_query(
            "UPDATE donors SET last_donation_date=%s WHERE id=%s",
            (donation_date, request.form["donor_id"])
        )
        flash("Donation record saved. Inventory is updated only after screening is marked Passed and a unit is created.")
        return redirect("/donations")

    rows = run_query("""
        SELECT d.id,don.donor_name,d.donation_date,d.blood_group,d.quantity_ml,
        d.screening_status,d.notes
        FROM donations d JOIN donors don ON d.donor_id=don.id
        ORDER BY d.id DESC
    """, fetch=True)

    return page("""
    <h2>Donation Records</h2>
    <div class="card"><h3>Record Donation</h3>
    <form method="post">
    <select name="donor_id" required>
    <option value="">Select Donor</option>
    {% for d in donors_list %}
    <option value="{{d.id}}">{{d.donor_name}} ({{d.blood_group}})</option>
    {% endfor %}
    </select>
    <label>Donation date <input type="date" name="donation_date" value="{{today}}" required></label>
    <input type="number" name="quantity_ml" value="450" min="1" placeholder="Quantity (ml)" required>
    <select name="screening_status"><option>Pending</option><option>Passed</option><option>Failed</option></select>
    <input name="notes" placeholder="Notes">
    <button>Save Donation</button>
    </form>
    <p class="muted">A donation record does not automatically create available stock. Create a stock unit only after the required screening and processing steps have been completed by authorized staff.</p>
    </div>
    <div class="card"><h3>Donation History</h3>{{table|safe}}</div>
    """, donors_list=donors_list, today=date.today().isoformat(), table=make_table(rows))


# -------------------- BLOOD INVENTORY --------------------

@app.route("/inventory", methods=["GET", "POST"])
@login_required
def inventory():
    refresh_expired_units()
    donations_list = run_query("""
        SELECT d.id,don.donor_name,d.blood_group,d.screening_status,d.donation_date
        FROM donations d JOIN donors don ON d.donor_id=don.id
        WHERE d.screening_status='Passed'
        ORDER BY d.id DESC
    """, fetch=True)

    if request.method == "POST":
        donation_id = request.form.get("donation_id") or None
        blood_group = request.form["blood_group"]
        component = request.form["component"]
        quantity = int(request.form["quantity_ml"])
        collection_date = request.form["collection_date"]
        expiry_date = request.form["expiry_date"]

        if quantity <= 0 or expiry_date <= collection_date:
            flash("Enter a positive quantity and an expiry date later than the collection date.")
            return redirect("/inventory")

        if donation_id:
            eligible = run_query("""
                SELECT id FROM donations
                WHERE id=%s AND screening_status='Passed' AND blood_group=%s
            """, (donation_id, blood_group), fetch=True)
            if not eligible:
                flash("Selected donation is not marked Passed or its blood group does not match.")
                return redirect("/inventory")

        run_query("""
            INSERT INTO blood_units
            (donation_id,blood_group,component,quantity_ml,collection_date,expiry_date,status)
            VALUES(%s,%s,%s,%s,%s,%s,'Available')
        """, (donation_id, blood_group, component, quantity, collection_date, expiry_date))
        flash("Inventory unit added.")
        return redirect("/inventory")

    rows = run_query("""
        SELECT id,donation_id,blood_group,component,quantity_ml,
        collection_date,expiry_date,status
        FROM blood_units ORDER BY expiry_date,id
    """, fetch=True)

    return page("""
    <h2>Blood Inventory</h2>
    <div class="card"><h3>Add Processed Blood Unit</h3>
    <form method="post">
    <select name="donation_id">
    <option value="">Manual / legacy record (no donation link)</option>
    {% for d in donations_list %}
    <option value="{{d.id}}">Donation #{{d.id}} - {{d.donor_name}} ({{d.blood_group}})</option>
    {% endfor %}
    </select>
    <select name="blood_group" required>{% for g in groups %}<option>{{g}}</option>{% endfor %}</select>
    <select name="component">{% for c in components %}<option>{{c}}</option>{% endfor %}</select>
    <input type="number" name="quantity_ml" min="1" value="450" required>
    <label>Collection date <input type="date" name="collection_date" value="{{today}}" required></label>
    <label>Expiry date <input type="date" name="expiry_date" required></label>
    <button>Add Stock Unit</button>
    </form>
    <p class="warning">Only add units that have completed all required screening, processing, labeling and quality-control procedures. The expiry date must be assigned by authorized blood-bank staff according to the applicable component and storage method.</p>
    </div>
    <div class="card"><h3>Inventory Records</h3>{{table|safe}}</div>
    """, donations_list=donations_list, groups=BLOOD_GROUPS,
    components=COMPONENTS, today=date.today().isoformat(), table=make_table(rows))


# -------------------- BLOOD REQUESTS --------------------

@app.route("/requests", methods=["GET", "POST"])
@login_required
def requests_page():
    hospitals_list = run_query(
        "SELECT id,hospital_name FROM hospitals ORDER BY hospital_name",
        fetch=True
    )

    if request.method == "POST":
        units = int(request.form["units_required"])
        if units <= 0:
            flash("Units required must be greater than zero.")
            return redirect("/requests")

        run_query("""
            INSERT INTO blood_requests
            (hospital_id,patient_reference,blood_group,component,units_required,
             request_date,required_by,urgency,status,notes)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'Pending',%s)
        """, (
            request.form.get("hospital_id") or None,
            request.form["patient_reference"], request.form["blood_group"],
            request.form["component"], units, date.today(),
            request.form.get("required_by") or None,
            request.form["urgency"], request.form["notes"]
        ))
        flash("Blood request recorded.")
        return redirect("/requests")

    rows = run_query("""
        SELECT r.id,h.hospital_name,r.patient_reference,r.blood_group,r.component,
        r.units_required,r.request_date,r.required_by,r.urgency,r.status,r.notes
        FROM blood_requests r LEFT JOIN hospitals h ON r.hospital_id=h.id
        ORDER BY r.id DESC
    """, fetch=True)

    return page("""
    <h2>Blood Requests</h2>
    <div class="card"><h3>Create Hospital Request</h3><form method="post">
    <select name="hospital_id"><option value="">Select Hospital</option>
    {% for h in hospitals_list %}<option value="{{h.id}}">{{h.hospital_name}}</option>{% endfor %}
    </select>
    <input name="patient_reference" placeholder="Patient reference / case ID">
    <select name="blood_group">{% for g in groups %}<option>{{g}}</option>{% endfor %}</select>
    <select name="component">{% for c in components %}<option>{{c}}</option>{% endfor %}</select>
    <input type="number" name="units_required" min="1" value="1" required>
    <label>Required by <input type="date" name="required_by"></label>
    <select name="urgency"><option>Normal</option><option>Urgent</option><option>Emergency</option></select>
    <input name="notes" placeholder="Additional notes">
    <button>Submit Request</button>
    </form></div>
    <div class="card"><h3>Request Records</h3>{{table|safe}}</div>
    """, hospitals_list=hospitals_list, groups=BLOOD_GROUPS,
    components=COMPONENTS, table=make_table(rows))


# -------------------- DISTRIBUTION / ISSUE --------------------

@app.route("/distribution", methods=["GET", "POST"])
@login_required
def distribution():
    refresh_expired_units()

    pending_requests = run_query("""
        SELECT r.id,r.blood_group,r.component,r.units_required,r.status,
        h.hospital_name,r.patient_reference
        FROM blood_requests r LEFT JOIN hospitals h ON r.hospital_id=h.id
        WHERE r.status IN ('Pending','Partially Fulfilled')
        ORDER BY r.id
    """, fetch=True)

    available_units = run_query("""
        SELECT id,blood_group,component,quantity_ml,expiry_date
        FROM blood_units
        WHERE status='Available' AND expiry_date >= %s
        ORDER BY expiry_date,id
    """, (date.today(),), fetch=True)

    if request.method == "POST":
        request_id = int(request.form["request_id"])
        unit_id = int(request.form["blood_unit_id"])

        con = get_connection()
        cur = con.cursor(dictionary=True)
        try:
            con.start_transaction()

            req_cur = con.execute if False else None
            cur.execute("""
                SELECT * FROM blood_requests WHERE id=%s FOR UPDATE
            """, (request_id,))
            req = cur.fetchone()

            cur.execute("""
                SELECT * FROM blood_units WHERE id=%s FOR UPDATE
            """, (unit_id,))
            unit = cur.fetchone()

            if not req or not unit:
                raise ValueError("Request or stock unit was not found.")

            if req["status"] not in ("Pending", "Partially Fulfilled"):
                raise ValueError("This request is not open for distribution.")

            if unit["status"] != "Available" or unit["expiry_date"] < date.today():
                raise ValueError("This blood unit is not available or has expired.")

            # This application deliberately checks exact group and component only.
            # It does not perform compatibility or crossmatch decisions.
            if unit["blood_group"] != req["blood_group"] or unit["component"] != req["component"]:
                raise ValueError("Selected stock does not exactly match the requested group and component.")

            cur.execute("""
                SELECT COUNT(*) AS issued FROM distributions WHERE request_id=%s
            """, (request_id,))
            issued = cur.fetchone()["issued"]

            if issued >= req["units_required"]:
                raise ValueError("The requested number of units has already been issued.")

            cur.execute("""
                INSERT INTO distributions
                (request_id,blood_unit_id,hospital_id,issue_date,issued_by,notes)
                VALUES(%s,%s,%s,%s,%s,%s)
            """, (
                request_id, unit_id, req["hospital_id"], date.today(),
                session.get("username"), request.form.get("notes", "")
            ))

            cur.execute("""
                UPDATE blood_units SET status='Issued' WHERE id=%s
            """, (unit_id,))

            new_issued = issued + 1
            new_status = "Fulfilled" if new_issued >= req["units_required"] else "Partially Fulfilled"
            cur.execute("UPDATE blood_requests SET status=%s WHERE id=%s", (new_status, request_id))

            con.commit()
            flash("Distribution recorded and inventory updated.")
        except (Error, ValueError) as e:
            con.rollback()
            flash(f"Distribution not completed: {e}")
        finally:
            cur.close()
            con.close()

        return redirect("/distribution")

    history = run_query("""
        SELECT x.id,x.request_id,x.blood_unit_id,x.hospital_id,h.hospital_name,
        x.issue_date,x.issued_by,x.notes
        FROM distributions x LEFT JOIN hospitals h ON x.hospital_id=h.id
        ORDER BY x.id DESC
    """, fetch=True)

    return page("""
    <h2>Blood Distribution</h2>
    <div class="card"><h3>Issue a Stock Unit Against a Request</h3>
    <form method="post">
    <select name="request_id" required>
    <option value="">Select open request</option>
    {% for r in requests %}
    <option value="{{r.id}}">Request #{{r.id}} - {{r.hospital_name or 'No hospital'}} -
    {{r.blood_group}} {{r.component}} ({{r.status}})</option>
    {% endfor %}
    </select>
    <select name="blood_unit_id" required>
    <option value="">Select available unit</option>
    {% for u in units %}
    <option value="{{u.id}}">Unit #{{u.id}} - {{u.blood_group}} {{u.component}} -
    {{u.expiry_date}} - {{u.quantity_ml}} ml</option>
    {% endfor %}
    </select>
    <input name="notes" placeholder="Issue notes">
    <button>Record Distribution</button>
    </form>
    <p class="warning">This demo checks exact blood group and component matching only. It does not determine transfusion compatibility, perform crossmatching, or authorize release. Qualified blood-bank staff must verify all clinical and regulatory requirements before any actual issue.</p>
    </div>
    <div class="card"><h3>Distribution History</h3>{{table|safe}}</div>
    """, requests=pending_requests, units=available_units, table=make_table(history))


# -------------------- EXPENSES --------------------

@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():
    if request.method == "POST":
        run_query("""
            INSERT INTO expenses(category,description,amount,expense_date)
            VALUES(%s,%s,%s,%s)
        """, (
            request.form["category"], request.form["description"],
            request.form["amount"], request.form["expense_date"]
        ))
        flash("Expense added.")
        return redirect("/expenses")

    rows = run_query("SELECT * FROM expenses ORDER BY expense_date DESC,id DESC", fetch=True)
    return page("""
    <h2>Expense Management</h2>
    <div class="card"><h3>Add Expense</h3><form method="post">
    <input name="category" placeholder="Category" required>
    <input name="description" placeholder="Description">
    <input type="number" step="0.01" name="amount" placeholder="Amount" required>
    <input type="date" name="expense_date" value="{{today}}" required>
    <button>Save Expense</button>
    </form></div>
    <div class="card"><h3>Expense Records</h3>{{table|safe}}</div>
    """, today=date.today().isoformat(), table=make_table(rows))


# -------------------- ANALYTICS --------------------

@app.route("/analytics")
@login_required
def analytics():
    refresh_expired_units()

    stock = run_query("""
        SELECT blood_group,component,COUNT(*) AS units,
        SUM(quantity_ml) AS total_ml
        FROM blood_units WHERE status='Available'
        GROUP BY blood_group,component ORDER BY blood_group,component
    """, fetch=True)

    donor_count = run_query("SELECT COUNT(*) AS n FROM donors", fetch=True)[0]["n"]
    request_count = run_query("SELECT COUNT(*) AS n FROM blood_requests", fetch=True)[0]["n"]
    expense_total = run_query(
        "SELECT COALESCE(SUM(amount),0) AS n FROM expenses", fetch=True
    )[0]["n"]

    stock_values = np.array([int(row["units"]) for row in stock], dtype=int)
    total_available = int(np.sum(stock_values))

    return page("""
    <h2>Inventory Analytics</h2>
    <div class="grid">
    <div class="stat">Registered Donors<strong>{{donors}}</strong></div>
    <div class="stat">Total Requests<strong>{{requests}}</strong></div>
    <div class="stat">Available Stock Units<strong>{{stock}}</strong></div>
    <div class="stat">Recorded Expenses<strong>â‚¹{{expenses}}</strong></div>
    </div>
    <div class="card"><h3>Available Stock by Blood Group and Component</h3>
    {{table|safe}}
    <p class="muted">NumPy is used to calculate the total available stock units.</p></div>
    """, donors=donor_count, requests=request_count,
    stock=total_available, expenses=expense_total, table=make_table(stock))


# -------------------- EXCEL REPORTS --------------------

@app.route("/reports")
@login_required
def reports():
    return page("""
    <h2>Reports</h2>
    <div class="card">
    <p>Export donor, hospital, donation, inventory, request, distribution and expense data to Excel.</p>
    <a class="btn" href="/export">Download Excel Report</a>
    </div>
    """)


@app.route("/export")
@login_required
def export():
    refresh_expired_units()
    queries = {
        "Donors": "SELECT * FROM donors",
        "Hospitals": "SELECT * FROM hospitals",
        "Donations": "SELECT * FROM donations",
        "Inventory": "SELECT * FROM blood_units",
        "Requests": "SELECT * FROM blood_requests",
        "Distribution": "SELECT * FROM distributions",
        "Expenses": "SELECT * FROM expenses"
    }

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet, sql in queries.items():
            data = run_query(sql, fetch=True)
            pd.DataFrame(data).to_excel(writer, sheet_name=sheet, index=False)

    output.seek(0)
    return send_file(
        output, as_attachment=True,
        download_name="Blood_Bank_Report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# -------------------- ERROR HANDLERS --------------------

@app.errorhandler(413)
def request_entity_too_large(_error):
    return "Uploaded request is too large.", 413


# -------------------- RUN APPLICATION --------------------

if __name__ == "__main__":
    try:
        initialize_database()
        refresh_expired_units()
        print("Blood Bank database connected successfully.")
        print("Open http://127.0.0.1:5000 in your browser.")
        app.run(debug=True)
    except Error as error:
        print("MYSQL CONNECTION ERROR:", error)
        print("Check MySQL service and DB_CONFIG password in main.py.")