from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash
import os
from werkzeug.utils import secure_filename
import sqlite3
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import urllib3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_key")

# --- RENDER SETUP ---
UPLOAD_FOLDER = 'uploads/notes'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATABASE = "database.db"

def get_db_connection():
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            semester TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            subject_id INTEGER,
            attended_classes INTEGER DEFAULT 0,
            total_classes INTEGER DEFAULT 0,
            FOREIGN KEY(student_id) REFERENCES users(id),
            FOREIGN KEY(subject_id) REFERENCES subjects(id)
        );
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT,
            action TEXT,
            timestamp TEXT
        );
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            youtube_link TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            year TEXT NOT NULL,
            subject TEXT NOT NULL,
            drive_link TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            subject TEXT NOT NULL,
            filename TEXT NOT NULL,
            uploader_email TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cgpa_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            semester_number INTEGER NOT NULL,
            credits INTEGER NOT NULL,
            sgpa REAL NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS credit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            course_code TEXT NOT NULL,
            course_name TEXT NOT NULL,
            credits INTEGER NOT NULL,
            grade TEXT NOT NULL,
            semester INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        
        -- NEW TABLES FOR FINANCE
        CREATE TABLE IF NOT EXISTS fee_structure (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester INTEGER UNIQUE NOT NULL,
            admission_fee INTEGER NOT NULL,
            campus_fee INTEGER NOT NULL,
            course_fee INTEGER NOT NULL,
            total_fee INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS student_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            semester INTEGER NOT NULL,
            status TEXT DEFAULT 'Not Paid',
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        
        -- CHANGED: Use double dashes for SQL comments instead of '#'
        -- NEW TABLE FOR HOLIDAYS --
        CREATE TABLE IF NOT EXISTS holidays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            holiday_date DATE NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            type TEXT NOT NULL
        );
    """)
    conn.commit()
    
    # Pre-insert Assam 2026 Official Holidays if table is empty
    c.execute("SELECT COUNT(*) FROM holidays")
    if c.fetchone()[0] == 0:
        default_holidays = [
            ('2026-01-14', 'Magh Bihu & Tusu Puja', 'Harvest festival', 'State'),
            ('2026-01-26', 'Republic Day', 'National holiday', 'National'),
            ('2026-03-03', 'Dol Jatra', 'Festival of colors', 'State'),
            ('2026-04-15', 'Bohag Bihu', 'Assamese New Year', 'State'),
            ('2026-08-15', 'Independence Day', 'National holiday', 'National'),
            ('2026-10-02', 'Gandhi Jayanti', 'Birthday of Mahatma Gandhi', 'National'),
            ('2026-10-18', 'Durga Puja', 'Kati Bihu & Durga Puja', 'State'),
            ('2026-12-25', 'Christmas Day', 'Christian festival', 'National')
        ]
        c.executemany("INSERT INTO holidays (holiday_date, name, description, type) VALUES (?, ?, ?, ?)", default_holidays)
        conn.commit()
        
    # Pre-insert default B.Tech Fee Structure from the provided image
    c.execute("SELECT COUNT(*) FROM fee_structure")
    if c.fetchone()[0] == 0:
        default_fees = [
            (1, 10000, 10000, 50000, 70000),
            (2, 10000, 10000, 40000, 60000),
            (3, 10000, 10000, 55000, 75000),
            (4, 10000, 10000, 45000, 65000),
            (5, 10000, 10000, 60000, 80000),
            (6, 10000, 10000, 50000, 70000),
            (7, 10000, 10000, 65000, 85000),
            (8, 10000, 10000, 55000, 75000)
        ]
        c.executemany("INSERT INTO fee_structure (semester, admission_fee, campus_fee, course_fee, total_fee) VALUES (?, ?, ?, ?, ?)", default_fees)
        conn.commit()

    # Create a default admin if no users exist
    c.execute("SELECT * FROM users")
    if not c.fetchone():
        c.execute("INSERT INTO users (email, password, is_admin) VALUES (?, ?, ?)", 
                  ("admin@admin.com", "admin123", 1))
        conn.commit()
        
    conn.close()

init_db()

# This hides annoying warning messages in your console about unverified SSL certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def fetch_astu_notices():
    """Scrapes the latest notices directly from ASTU's official website using smart filtering."""
    url = "https://astu.ac.in/?page_id=561" 
    notices = []
    
    try:
        # Disguise the Python script as a real web browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=5, verify=False) 
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Scan ALL links on the page
        for link in soup.find_all('a'):
            title = link.text.strip()
            href = link.get('href', '')
            
            # Rule: Real notices usually have longer text and contain specific keywords
            is_valid_notice = len(title) > 15 and (
                "notice" in title.lower() or 
                "notification" in title.lower() or 
                "result" in title.lower() or 
                "schedule" in title.lower() or 
                "fee" in title.lower() or
                "registration" in title.lower() or
                "convocation" in title.lower()
            )
            
            if is_valid_notice and href:
                # Prevent adding the exact same notice twice
                if not any(n['title'] == title for n in notices):
                    notices.append({
                        "title": title,
                        # Make sure relative links are converted to full clickable URLs
                        "link": href if href.startswith('http') else f"https://astu.ac.in/{href.lstrip('/')}",
                        "date": "Latest Update"
                    })
                    
            if len(notices) >= 3: # Stop after getting the top 3
                break
                
    except Exception as e:
        print(f"Error fetching ASTU notices: {e}")
        notices = [{"title": "ASTU site currently unreachable. Check back later.", "link": "https://astu.ac.in/?page_id=561", "date": "Error"}]
        
    return notices
# ==========================================
# CORE ROUTES
# ==========================================
@app.route("/")
def home():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get current date
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Upcoming holidays
    c.execute("""
        SELECT id, holiday_date, name, description, type 
        FROM holidays 
        WHERE holiday_date >= ? 
        ORDER BY holiday_date ASC
    """, (today,))
    upcoming_raw = c.fetchall()
    
    # Past holidays
    c.execute("""
        SELECT id, holiday_date, name, description, type 
        FROM holidays 
        WHERE holiday_date < ? 
        ORDER BY holiday_date DESC
    """, (today,))
    past_raw = c.fetchall()

    # --- NEW DASHBOARD STATS LOGIC ---
    overall_cgpa = "0.00"
    total_credits = 0
    fee_balance = "0.00"
    payment_status = "Fully Paid"

    if "user_id" in session:
        user_id = session["user_id"]

        # 1. Calculate CGPA
        c.execute("SELECT credits, sgpa FROM cgpa_records WHERE user_id = ?", (user_id,))
        cgpa_records = c.fetchall()
        if cgpa_records:
            cgpa_credits = sum(r[0] for r in cgpa_records)
            weighted_sum = sum(r[0] * r[1] for r in cgpa_records)
            overall_cgpa = f"{(weighted_sum / cgpa_credits):.2f}" if cgpa_credits > 0 else "0.00"

        # 2. Calculate Credits
        c.execute("SELECT SUM(credits) FROM credit_history WHERE user_id = ?", (user_id,))
        credits_result = c.fetchone()
        total_credits = credits_result[0] if credits_result and credits_result[0] else 0

        # 3. Calculate Fee Balance
        c.execute("SELECT semester, total_fee FROM fee_structure")
        all_fees = c.fetchall()
        
        c.execute("SELECT semester, status FROM student_payments WHERE user_id=?", (user_id,))
        payments = {row[0]: row[1] for row in c.fetchall()}
        
        total_due = 0
        for fee in all_fees:
            sem = fee[0]
            total = fee[1]
            status = payments.get(sem, 'Not Paid')
            if status != 'Paid':
                total_due += total
        
        fee_balance = f"{total_due:,.2f}"
        payment_status = "Fully Paid" if total_due == 0 else "Dues Pending"
    # ---------------------------------
        
    # 1. Fetch live ASTU notices!
    live_notices = fetch_astu_notices()

    conn.close()
    
    def process_holidays(h_list):
        processed = []
        for h in h_list:
            d = datetime.strptime(h[1], '%Y-%m-%d')
            processed.append({
                "id": h[0],
                "month": d.strftime('%b').upper(),
                "day": d.strftime('%d'),
                "name": h[2],
                "description": h[3],
                "type": h[4]
            })
        return processed

    return render_template(
        "index.html",
        upcoming_holidays=process_holidays(upcoming_raw),
        past_holidays=process_holidays(past_raw),
        overall_cgpa=overall_cgpa,
        total_credits=total_credits,
        fee_balance=fee_balance,
        payment_status=payment_status,
        astu_notices=live_notices
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form["password"]
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
        user = c.fetchone()
        conn.close()
        
        if user:
            session["user_id"] = user[0]
            session["email"] = email
            session["is_admin"] = bool(user[3])
            log_action(email, "Logged In")
            return redirect(url_for("home"))
        else:
            return "Invalid credentials"
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_db_connection()
        c = conn.cursor()

        c.execute("SELECT * FROM users WHERE email = ?", (email,))
        if c.fetchone():
            conn.close()
            return "⚠️ Email already registered. Try logging in."

        c.execute("INSERT INTO users (email, password, is_admin) VALUES (?, ?, ?)",
                  (email, password, 0))
        conn.commit()
        log_action(email, "Registered")
        conn.close()
        return redirect("/login")
    
    return render_template("register.html")

# ==========================================
# CGPA TRACKER ROUTES
# ==========================================
@app.route("/cgpa")
def view_cgpa():
    if "user_id" not in session:
        return redirect(url_for("login"))
        
    user_id = session["user_id"]
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, semester_number, credits, sgpa FROM cgpa_records WHERE user_id = ? ORDER BY semester_number", (user_id,))
    records = c.fetchall()
    
    semesters = [{"id": r[0], "semester_number": r[1], "credits": r[2], "sgpa": r[3]} for r in records]
    
    total_credits = sum(s["credits"] for s in semesters)
    weighted_sum = sum(s["credits"] * s["sgpa"] for s in semesters)
    overall_cgpa = f"{(weighted_sum / total_credits):.2f}" if total_credits > 0 else "0.00"
    
    conn.close()
    return render_template("cgpa.html", semesters=semesters, overall_cgpa=overall_cgpa, total_credits=total_credits)

@app.route("/cgpa/add", methods=["GET", "POST"])
def add_cgpa():
    if "user_id" not in session:
        return redirect(url_for("login"))
        
    if request.method == "POST":
        semester_number = request.form["semester_number"]
        credits = request.form["credits"]
        sgpa = request.form["sgpa"]
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO cgpa_records (user_id, semester_number, credits, sgpa) VALUES (?, ?, ?, ?)",
                  (session["user_id"], semester_number, credits, sgpa))
        conn.commit()
        conn.close()
        return redirect(url_for("view_cgpa"))
        
    return render_template("add_cgpa.html")

@app.route("/cgpa/delete/<int:record_id>")
def delete_cgpa(record_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
        
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM cgpa_records WHERE id = ? AND user_id = ?", (record_id, session["user_id"]))
    conn.commit()
    conn.close()
    return redirect(url_for("view_cgpa"))

# ==========================================
# CREDITS TRACKER ROUTES
# ==========================================
@app.route("/credits")
def view_credits():
    if "user_id" not in session:
        return redirect(url_for("login"))
        
    user_id = session["user_id"]
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, course_code, course_name, credits, grade, semester FROM credit_history WHERE user_id = ? ORDER BY semester, course_code", (user_id,))
    records = c.fetchall()
    
    credit_history = [{"id": r[0], "course_code": r[1], "course_name": r[2], "credits": r[3], "grade": r[4], "semester": r[5]} for r in records]
    
    total_credits = sum(r["credits"] for r in credit_history)
    completion_percentage = round((total_credits / 160) * 100) if total_credits > 0 else 0
    
    conn.close()
    return render_template("credits.html", credit_history=credit_history, total_credits=total_credits, completion_percentage=completion_percentage)

@app.route("/credits/add", methods=["GET", "POST"])
def add_credits():
    if "user_id" not in session:
        return redirect(url_for("login"))
        
    if request.method == "POST":
        course_code = request.form["course_code"]
        course_name = request.form["course_name"]
        credits = request.form["credits"]
        grade = request.form["grade"]
        semester = request.form["semester"]
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO credit_history (user_id, course_code, course_name, credits, grade, semester) VALUES (?, ?, ?, ?, ?, ?)",
                  (session["user_id"], course_code, course_name, credits, grade, semester))
        conn.commit()
        conn.close()
        return redirect(url_for("view_credits"))
        
    return render_template("add_credits.html")
    
@app.route("/credits/delete/<int:record_id>")
def delete_credit(record_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
        
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM credit_history WHERE id = ? AND user_id = ?", (record_id, session["user_id"]))
    conn.commit()
    conn.close()
    return redirect(url_for("view_credits"))

# ==========================================
# RESOURCE ROUTES (Courses, Papers, Notes)
# ==========================================
@app.route("/courses")
def courses():
    search_query = request.args.get("q", "")
    conn = get_db_connection()
    c = conn.cursor()
    if search_query:
        c.execute("SELECT * FROM courses WHERE name LIKE ?", ('%' + search_query + '%',))
    else:
        c.execute("SELECT * FROM courses")
    courses = c.fetchall()
    conn.close()
    return render_template("courses.html", courses=courses, query=search_query)

@app.route("/courses/add", methods=["GET", "POST"])
def add_course():
    if not session.get("is_admin"):
        return redirect(url_for("login"))
    if request.method == "POST":
        name = request.form["name"]
        link = request.form["youtube_link"]
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO courses (name, youtube_link) VALUES (?, ?)", (name, link))
        conn.commit()
        conn.close()
        return redirect(url_for("courses"))
    return render_template("add_course.html")

@app.route("/courses/edit/<int:id>", methods=["GET", "POST"])
def edit_course(id):
    if not session.get("is_admin"):
        return redirect(url_for("login"))
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == "POST":
        name = request.form["name"]
        link = request.form["youtube_link"]
        c.execute("UPDATE courses SET name=?, youtube_link=? WHERE id=?", (name, link, id))
        conn.commit()
        conn.close()
        return redirect(url_for("courses"))
    c.execute("SELECT * FROM courses WHERE id=?", (id,))
    course = c.fetchone()
    conn.close()
    return render_template("edit_course.html", course=course)

@app.route("/courses/delete/<int:id>")
def delete_course(id):
    if not session.get("is_admin"):
        return redirect(url_for("login"))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM courses WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("courses"))

@app.route("/papers")
def papers():
    search_query = request.args.get("q", "")
    conn = get_db_connection()
    c = conn.cursor()

    if search_query:
        query_like = '%' + search_query + '%'
        c.execute("""
            SELECT * FROM papers 
            WHERE subject LIKE ? OR semester LIKE ? OR year LIKE ? 
            ORDER BY semester, year, subject
        """, (query_like, query_like, query_like))
    else:
        c.execute("SELECT * FROM papers ORDER BY semester, year, subject")

    all_papers = c.fetchall()
    conn.close()
    return render_template("papers.html", papers=all_papers, query=search_query)

@app.route("/papers/add", methods=["GET", "POST"])
def add_paper():
    if not session.get("is_admin"):
        return redirect("/login")
    if request.method == "POST":
        semester = request.form["semester"]
        year = request.form["year"]
        subject = request.form["subject"]
        drive_link = request.form["drive_link"]

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO papers (semester, year, subject, drive_link) VALUES (?, ?, ?, ?)",
                  (semester, year, subject, drive_link))
        conn.commit()
        conn.close()
        return redirect("/papers")
    return render_template("add_paper.html")

@app.route("/papers/edit/<int:paper_id>", methods=["GET", "POST"])
def edit_paper(paper_id):
    if not session.get("is_admin"):
        return redirect("/login")
    
    conn = get_db_connection()
    c = conn.cursor()
    
    if request.method == "POST":
        semester = request.form["semester"]
        year = request.form["year"]
        subject = request.form["subject"]
        drive_link = request.form["drive_link"]

        c.execute("""
            UPDATE papers
            SET semester=?, year=?, subject=?, drive_link=?
            WHERE id=?
        """, (semester, year, subject, drive_link, paper_id))
        
        conn.commit()
        conn.close()
        return redirect("/papers")

    c.execute("SELECT * FROM papers WHERE id=?", (paper_id,))
    paper = c.fetchone()
    conn.close()
    return render_template("edit_paper.html", paper=paper)

@app.route("/papers/delete/<int:paper_id>")
def delete_paper(paper_id):
    if not session.get("is_admin"):
        return redirect("/login")
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM papers WHERE id=?", (paper_id,))
    conn.commit()
    conn.close()
    return redirect("/papers")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/notes')
def notes():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, semester, subject, filename, uploader_email FROM notes")
    notes_data = c.fetchall()
    conn.close()
    return render_template('notes.html', notes=notes_data)

@app.route('/notes/add', methods=['GET', 'POST'])
def add_notes():
    if 'email' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        semester = request.form['semester']
        subject = request.form['subject']
        file = request.files['file']

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            uploader_email = session.get('email')

            conn = get_db_connection()
            c = conn.cursor()
            c.execute(
                "INSERT INTO notes (semester, subject, filename, uploader_email) VALUES (?, ?, ?, ?)",
                (semester, subject, filename, uploader_email)
            )
            conn.commit()
            conn.close()

        return redirect(url_for('notes'))

    return render_template('add_notes.html')

@app.route('/notes/delete/<int:note_id>')
def delete_note(note_id):
    if "email" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT filename, uploader_email FROM notes WHERE id=?", (note_id,))
    note = c.fetchone()

    if not note:
        conn.close()
        return "Note not found", 404

    filename, uploader_email = note

    if not session.get("is_admin") and session["email"] != uploader_email:
        conn.close()
        return "Unauthorized", 403

    c.execute("DELETE FROM notes WHERE id=?", (note_id,))
    conn.commit()
    conn.close()

    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    return redirect(url_for("notes"))

@app.route('/notes/download/<int:note_id>')
def download_notes(note_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT semester, subject, filename FROM notes WHERE id=?", (note_id,))
    note = c.fetchone()
    conn.close()

    if note:
        semester, subject, filename = note
        ext = filename.rsplit('.', 1)[1]
        nice_name = f"Semester{semester}_{subject.replace(' ', '_')}.{ext}"

        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            filename,
            as_attachment=True,
            download_name=nice_name
        )
    return "File not found", 404

# ==========================================
# SYSTEM / LOGS / AUTH ROUTES
# ==========================================
def log_action(user_email, action):
    conn = get_db_connection()
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO logs (user_email, action, timestamp) VALUES (?, ?, ?)",
              (user_email, action, timestamp))
    conn.commit()
    conn.close()

@app.route("/logs")
def view_logs():
    if not session.get("is_admin"):
        return "Unauthorized", 403

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT user_email, action, timestamp FROM logs ORDER BY id DESC")
    logs = c.fetchall()
    conn.close()
    return render_template("view_logs.html", logs=logs)

@app.route("/users")
def view_users():
    if not session.get("is_admin"):
        return "Unauthorized", 403

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, email, is_admin FROM users")
    users = c.fetchall()
    conn.close()
    return render_template("view_users.html", users=users)

@app.route("/delete_user/<int:user_id>")
def delete_user(user_id):
    if not session.get("is_admin"):
        return "Unauthorized", 403
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("view_users"))

# ==========================================
# FINANCE TRACKER ROUTES
# ==========================================
@app.route('/finance')
def finance():
    if "user_id" not in session:
        return redirect(url_for("login"))
        
    user_id = session["user_id"]
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get the official fee structure
    c.execute("SELECT semester, admission_fee, campus_fee, course_fee, total_fee FROM fee_structure ORDER BY semester")
    fee_structure = c.fetchall()
    
    # Get the current user's payment status
    c.execute("SELECT semester, status FROM student_payments WHERE user_id=?", (user_id,))
    payments = {row[0]: row[1] for row in c.fetchall()}
    
    finance_data = []
    total_paid = 0
    total_due = 0
    
    for fee in fee_structure:
        sem = fee[0]
        status = payments.get(sem, 'Not Paid')
        total = fee[4]
        
        if status == 'Paid':
            total_paid += total
        else:
            total_due += total
            
        finance_data.append({
            'semester': sem,
            'admission_fee': fee[1],
            'campus_fee': fee[2],
            'course_fee': fee[3],
            'total_fee': total,
            'status': status
        })
        
    conn.close()
    return render_template('finance.html', finance_data=finance_data, total_paid=total_paid, total_due=total_due)

@app.route('/finance/toggle', methods=['POST'])
def toggle_payment():
    if "user_id" not in session:
        return redirect(url_for("login"))
        
    user_id = session["user_id"]
    semester = request.form.get('semester')
    status = request.form.get('status')
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if a payment record already exists for this semester
    c.execute("SELECT id FROM student_payments WHERE user_id=? AND semester=?", (user_id, semester))
    record = c.fetchone()
    
    if record:
        c.execute("UPDATE student_payments SET status=? WHERE id=?", (status, record[0]))
    else:
        c.execute("INSERT INTO student_payments (user_id, semester, status) VALUES (?, ?, ?)", (user_id, semester, status))
        
    conn.commit()
    conn.close()
    
    return redirect(url_for('finance'))

@app.route('/finance/manage')
def manage_finance():
    if not session.get("is_admin"):
        return redirect(url_for("home"))
        
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT semester, admission_fee, campus_fee, course_fee, total_fee FROM fee_structure ORDER BY semester")
    fee_structure = c.fetchall()
    conn.close()
    
    return render_template('manage_finance.html', fee_structure=fee_structure)

@app.route('/finance/edit/<int:semester>', methods=['GET', 'POST'])
def edit_finance(semester):
    if not session.get("is_admin"):
        return redirect(url_for("home"))
        
    conn = get_db_connection()
    c = conn.cursor()
    
    if request.method == 'POST':
        # Grab the updated fees from the form
        admission_fee = int(request.form['admission_fee'])
        campus_fee = int(request.form['campus_fee'])
        course_fee = int(request.form['course_fee'])
        
        # Auto-calculate the total so the admin doesn't have to
        total_fee = admission_fee + campus_fee + course_fee
        
        c.execute("""
            UPDATE fee_structure 
            SET admission_fee=?, campus_fee=?, course_fee=?, total_fee=? 
            WHERE semester=?
        """, (admission_fee, campus_fee, course_fee, total_fee, semester))
        
        conn.commit()
        conn.close()
        return redirect(url_for('manage_finance'))
        
    # GET request: fetch the current fees to pre-fill the form
    c.execute("SELECT semester, admission_fee, campus_fee, course_fee FROM fee_structure WHERE semester=?", (semester,))
    fee = c.fetchone()
    conn.close()
    
    if not fee:
        return "Semester not found", 404
        
    return render_template('edit_finance.html', fee=fee)

# ==========================================
# HOLIDAY MANAGEMENT ROUTES (Admin)
# ==========================================
@app.route("/holidays/manage")
def manage_holidays():
    if not session.get("is_admin"):
        return redirect(url_for("home"))
        
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, holiday_date, name, description, type FROM holidays ORDER BY holiday_date DESC")
    holidays = c.fetchall()
    conn.close()
    
    return render_template("manage_holidays.html", holidays=holidays)

@app.route("/holidays/add", methods=["POST"])
def add_holiday():
    if not session.get("is_admin"):
        return redirect(url_for("home"))
        
    date = request.form["date"]
    name = request.form["name"]
    desc = request.form["description"]
    h_type = request.form["type"]
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO holidays (holiday_date, name, description, type) VALUES (?, ?, ?, ?)", 
              (date, name, desc, h_type))
    conn.commit()
    conn.close()
    return redirect(url_for("manage_holidays"))

@app.route("/holidays/delete/<int:h_id>")
def delete_holiday(h_id):
    if not session.get("is_admin"):
        return redirect(url_for("home"))
        
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM holidays WHERE id=?", (h_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("manage_holidays"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)