from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
from backend import database
import psycopg2
import psycopg2.extensions
import bcrypt
import os
import shutil
import uuid
import re
from datetime import datetime
from fpdf import FPDF

app = FastAPI(title="Artiverse API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "public")

# Serve ALL frontend static files (css, js, html) at root level
app.mount("/styles", StaticFiles(directory=os.path.join(FRONTEND_DIR, "styles")), name="styles")
app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")

# Serve individual HTML pages
@app.get("/")
@app.get("/index.html")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/admin.html")
def serve_admin():
    return FileResponse(os.path.join(FRONTEND_DIR, "admin.html"))

@app.get("/artist.html")
def serve_artist():
    return FileResponse(os.path.join(FRONTEND_DIR, "artist.html"))

@app.get("/signup.html")
def serve_signup():
    return FileResponse(os.path.join(FRONTEND_DIR, "signup.html"))

def save_upload_file(upload_file: UploadFile) -> str:
    if not upload_file:
        return ""
    filename = f"{uuid.uuid4()}_{upload_file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return f"/uploads/{filename}"

database.init_db()

def get_db():
    conn = database.get_db_connection()
    try:
        yield conn
    finally:
        conn.close()

def get_role(authorization: str) -> str:
    """Returns role string from token like '1_Admin' or '2_Artist'"""
    try:
        return authorization.split('_')[1]
    except (IndexError, AttributeError):
        return ""

def get_user_id(authorization: str) -> int:
    try:
        return int(authorization.split('_')[0])
    except (IndexError, ValueError, AttributeError):
        return -1

# --- POSTGRES MIGRATION HELPER ---
# Maps PostgreSQL's automatic lowercase columns back to the PascalCase expected by the frontend
KEY_MAP = {
    'userid': 'UserID', 'name': 'Name', 'role': 'Role', 'email': 'Email',
    'passwordhash': 'PasswordHash', 'contactinfo': 'ContactInfo', 'accountstatus': 'AccountStatus',
    'portfolioid': 'PortfolioID', 'artistid': 'ArtistID', 'imageurl': 'ImageURL',
    'artstyletags': 'ArtStyleTags', 'dateuploaded': 'DateUploaded',
    'tenderid': 'TenderID', 'title': 'Title', 'description': 'Description',
    'totalbudget': 'TotalBudget', 'platformcommission': 'PlatformCommission',
    'payoutamount': 'PayoutAmount', 'deadline': 'Deadline', 'status': 'Status',
    'assignedartistid': 'AssignedArtistID', 'adminid': 'AdminID', 'createdat': 'CreatedAt',
    'applicationid': 'ApplicationID', 'appliedat': 'AppliedAt',
    'milestoneid': 'MilestoneID', 'phasename': 'PhaseName', 'proofimageurl': 'ProofImageURL',
    'geotagdata': 'GeoTagData',
    'ratingid': 'RatingID', 'qualityscore': 'QualityScore', 'capacitytag': 'CapacityTag',
    'logid': 'LogID', 'timestamp': 'Timestamp', 'actiontaken': 'ActionTaken',
    'justification': 'Justification',
    'tendertitle': 'TenderTitle', 'artistname': 'ArtistName', 'adminname': 'AdminName'
}

def format_row(row):
    """Converts db row lowercase keys to PascalCase and handles datetime serialization."""
    if not row:
        return row
    formatted = {}
    for k, v in dict(row).items():
        mapped_key = KEY_MAP.get(k, k)
        # Convert datetime to string to ensure standard JSON serialization
        if isinstance(v, datetime):
            formatted[mapped_key] = v.isoformat()
        else:
            formatted[mapped_key] = v
    return formatted
# ---------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/auth/login")
def login(req: LoginRequest, db: psycopg2.extensions.connection = Depends(get_db)):
    c = db.cursor()
    c.execute("SELECT UserID, Name, Role, AccountStatus, PasswordHash FROM Users WHERE Email = %s", (req.email,))
    row = c.fetchone()
    
    if row:
        user = format_row(row)
        try:
            password_valid = bcrypt.checkpw(req.password.encode('utf-8'), user['PasswordHash'].encode('utf-8'))
        except Exception:
            password_valid = (req.password == user['PasswordHash'])

        if not password_valid:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if user['AccountStatus'] != 'Active':
            raise HTTPException(status_code=403, detail="Account is pending or suspended.")

        return {
            "token": f"{user['UserID']}_{user['Role']}",
            "user": {
                "UserID": user['UserID'],
                "Name": user['Name'],
                "Role": user['Role'],
                "AccountStatus": user['AccountStatus']
            }
        }
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/api/auth/signup")
def signup(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    contact_info: str = Form(None),
    art_style_tags: str = Form(None),
    portfolio_image: UploadFile = File(...),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    c = db.cursor()
    c.execute("SELECT UserID FROM Users WHERE Email = %s", (email,))
    if c.fetchone():
        raise HTTPException(status_code=400, detail="Email already registered")

    image_url = save_upload_file(portfolio_image)

    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    c.execute('''INSERT INTO Users (Name, Role, Email, PasswordHash, ContactInfo, AccountStatus)
                 VALUES (%s, %s, %s, %s, %s, %s) RETURNING UserID''',
              (name, 'Artist', email, hashed_pw, contact_info, 'Active'))
    user_id = format_row(c.fetchone())['UserID']

    c.execute('INSERT INTO Portfolios (ArtistID, ImageURL, ArtStyleTags) VALUES (%s, %s, %s)', (user_id, image_url, art_style_tags))
    c.execute('INSERT INTO Performance (ArtistID, QualityScore, CapacityTag) VALUES (%s, %s, %s)', (user_id, 70, 'Available'))

    db.commit()
    return {"message": "Signup successful. Your account is active."}

@app.get("/api/admin/users/pending")
def get_pending_users(authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Admin':
        raise HTTPException(status_code=403, detail="Unauthorized")
    c = db.cursor()
    c.execute("SELECT UserID, Name, Email, ContactInfo, AccountStatus FROM Users WHERE AccountStatus = 'Pending'")
    return [format_row(row) for row in c.fetchall()]

@app.get("/api/admin/users")
def get_all_users(authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Admin':
        raise HTTPException(status_code=403, detail="Unauthorized")
    c = db.cursor()
    c.execute("""
        SELECT u.UserID, u.Name, u.Email, u.Role, u.AccountStatus,
               p.QualityScore, p.CapacityTag, port.ArtStyleTags
        FROM Users u
        LEFT JOIN Performance p ON u.UserID = p.ArtistID
        LEFT JOIN Portfolios port ON u.UserID = port.ArtistID
        ORDER BY u.Role, u.Name
    """)
    return [format_row(row) for row in c.fetchall()]

@app.post("/api/admin/users/{user_id}/approve")
def approve_user(user_id: int, authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Admin':
        raise HTTPException(status_code=403, detail="Unauthorized")

    c = db.cursor()
    c.execute("UPDATE Users SET AccountStatus = 'Active' WHERE UserID = %s", (user_id,))
    if c.rowcount == 0:
        raise HTTPException(status_code=404, detail="User not found")

    db.commit()
    return {"message": "User approved"}

@app.get("/api/tenders")
def get_tenders(db: psycopg2.extensions.connection = Depends(get_db)):
    c = db.cursor()
    # Filter out corrupted dates that cause Python's datetime to overflow
    c.execute("SELECT * FROM Tenders WHERE EXTRACT(YEAR FROM Deadline) < 9999 ORDER BY CreatedAt DESC")
    return [format_row(row) for row in c.fetchall()]

class TenderCreate(BaseModel):
    title: str
    description: str
    total_budget: float
    platform_commission: float
    deadline: str

@app.post("/api/tenders")
def create_tender(req: TenderCreate, authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Admin':
        raise HTTPException(status_code=403, detail="Unauthorized")
    admin_id = get_user_id(authorization)

    payout = req.total_budget - (req.total_budget * (req.platform_commission / 100))

    c = db.cursor()
    c.execute('''INSERT INTO Tenders (Title, Description, TotalBudget, PlatformCommission, PayoutAmount, Deadline, AdminID)
                 VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING TenderID''',
              (req.title, req.description, req.total_budget, req.platform_commission, payout, req.deadline, admin_id))
    tender_id = format_row(c.fetchone())['TenderID']

    c.execute('''INSERT INTO AuditLogs (AdminID, TenderID, ActionTaken, Justification)
                 VALUES (%s, %s, %s, %s)''',
              (admin_id, tender_id, 'CREATED_TENDER', 'New tender created'))
    db.commit()
    return {"message": "Tender created successfully", "TenderID": tender_id}

@app.get("/api/tenders/open")
def get_open_tenders(authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Artist':
        raise HTTPException(status_code=403, detail="Unauthorized")
    artist_id = get_user_id(authorization)
    c = db.cursor()

    current_time = datetime.now().isoformat()
    c.execute("""
        SELECT t.* FROM Tenders t
        WHERE t.Status = 'Open'
        AND t.Deadline > %s
        AND t.TenderID NOT IN (SELECT TenderID FROM Applications WHERE ArtistID = %s)
        ORDER BY t.Deadline ASC
    """, (current_time, artist_id,))
    return [format_row(row) for row in c.fetchall()]

@app.post("/api/tenders/{tender_id}/apply")
def apply_tender(tender_id: int, authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Artist':
        raise HTTPException(status_code=403, detail="Unauthorized")
    artist_id = get_user_id(authorization)

    c = db.cursor()
    c.execute("SELECT Status, Deadline FROM Tenders WHERE TenderID = %s", (tender_id,))
    row = c.fetchone()
    
    if not row:
        raise HTTPException(status_code=400, detail="Tender not found.")
        
    tender = format_row(row)

    if tender['Status'] != 'Open':
        raise HTTPException(status_code=400, detail="Tender is not available.")

    # Ensure deadline comparison handles psycopg2 datetime objects securely
    tender_deadline = tender['Deadline']
    if isinstance(tender_deadline, str):
        tender_deadline = datetime.fromisoformat(tender_deadline)
        
    if tender_deadline < datetime.now():
        raise HTTPException(status_code=400, detail="Deadline has passed.")

    try:
        c.execute("INSERT INTO Applications (TenderID, ArtistID) VALUES (%s, %s)", (tender_id, artist_id))
        db.commit()
    except psycopg2.IntegrityError:
        raise HTTPException(status_code=400, detail="Already applied.")

    return {"message": "Successfully applied for the tender."}

@app.get("/api/tenders/{tender_id}/candidates")
def get_candidates(tender_id: int, db: psycopg2.extensions.connection = Depends(get_db)):
    c = db.cursor()

    c.execute("SELECT Description, Deadline FROM Tenders WHERE TenderID = %s", (tender_id,))
    row = c.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tender not found")
        
    tender = format_row(row)

    tender_desc = tender['Description'].lower() if tender['Description'] else ""
    tender_keywords = set(re.findall(r'\b\w+\b', tender_desc))

    c.execute('''
        SELECT u.UserID, u.Name, p.QualityScore, p.CapacityTag, port.ArtStyleTags, port.ImageURL
        FROM Users u
        JOIN Applications a ON u.UserID = a.ArtistID
        LEFT JOIN Performance p ON u.UserID = p.ArtistID
        LEFT JOIN Portfolios port ON u.UserID = port.ArtistID
        WHERE u.Role = 'Artist' AND u.AccountStatus = 'Active' AND a.TenderID = %s
    ''', (tender_id,))
    
    all_artists = [format_row(r) for r in c.fetchall()]

    scored_candidates = []
    for artist in all_artists:
        tags = artist['ArtStyleTags'] or ""
        artist_tags = set(re.findall(r'\b\w+\b', tags.lower()))

        match_count = len(tender_keywords.intersection(artist_tags))
        ai_score = (match_count * 100) + (artist['QualityScore'] or 0)

        artist['QualityScore'] = ai_score
        scored_candidates.append(artist)

    scored_candidates.sort(key=lambda x: x['QualityScore'], reverse=True)
    return scored_candidates[:5]

class AwardRequest(BaseModel):
    artist_id: int
    justification: str

@app.post("/api/tenders/{tender_id}/award")
def award_tender(tender_id: int, req: AwardRequest, authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Admin':
        raise HTTPException(status_code=403, detail="Unauthorized")
    admin_id = get_user_id(authorization)

    c = db.cursor()
    c.execute("SELECT Status FROM Tenders WHERE TenderID = %s", (tender_id,))
    row = c.fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="Tender not found")
        
    tender = format_row(row)
    if tender['Status'] != 'Open':
        raise HTTPException(status_code=400, detail="Tender is not open")

    c.execute("UPDATE Tenders SET Status = 'Assigned', AssignedArtistID = %s WHERE TenderID = %s", (req.artist_id, tender_id))

    c.execute('''INSERT INTO AuditLogs (AdminID, TenderID, ActionTaken, Justification)
                 VALUES (%s, %s, %s, %s)''',
              (admin_id, tender_id, 'AWARDED_CONTRACT', req.justification))

    c.execute('''INSERT INTO Milestones (TenderID, PhaseName) VALUES (%s, %s)''', (tender_id, '25% Upfront Verification'))
    db.commit()
    return {"message": "Contract awarded successfully"}

@app.get("/api/tenders/{tender_id}/milestones")
def get_tender_milestones(tender_id: int, db: psycopg2.extensions.connection = Depends(get_db)):
    c = db.cursor()
    c.execute("SELECT * FROM Milestones WHERE TenderID = %s", (tender_id,))
    return [format_row(row) for row in c.fetchall()]

@app.post("/api/milestones/{milestone_id}/submit")
def submit_milestone(
    milestone_id: int,
    geo_tag_data: str = Form(...),
    proof_image: UploadFile = File(...),
    authorization: str = Header(None),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    if not authorization or get_role(authorization) != 'Artist':
        raise HTTPException(status_code=403, detail="Unauthorized")

    image_url = save_upload_file(proof_image)

    c = db.cursor()
    c.execute("UPDATE Milestones SET Status = 'Submitted', ProofImageURL = %s, GeoTagData = %s WHERE MilestoneID = %s",
              (image_url, geo_tag_data, milestone_id))

    if c.rowcount == 0:
        raise HTTPException(status_code=404, detail="Milestone not found")

    db.commit()
    return {"message": "Milestone submitted successfully"}

@app.get("/api/auditlogs")
def get_audit_logs(authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Admin':
        raise HTTPException(status_code=403, detail="Unauthorized")
    c = db.cursor()
    c.execute("SELECT * FROM AuditLogs ORDER BY Timestamp DESC")
    return [format_row(row) for row in c.fetchall()]

@app.get("/api/auditlogs/export")
def export_audit_logs(authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Admin':
        raise HTTPException(status_code=403, detail="Unauthorized")

    c = db.cursor()
    c.execute("""
        SELECT a.LogID, a.Timestamp, u.Name as AdminName, a.TenderID, a.ActionTaken, a.Justification
        FROM AuditLogs a
        LEFT JOIN Users u ON a.AdminID = u.UserID
        ORDER BY a.Timestamp DESC
    """)
    logs = [format_row(row) for row in c.fetchall()]

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(200, 10, txt="Artiverse - Immutable Audit Ledger Report", ln=1, align='C')
    pdf.ln(10)

    pdf.set_font("helvetica", size=10)
    for log in logs:
        text = f"[{log['Timestamp']}] Admin: {log['AdminName']} | Tender: {log['TenderID']} | Action: {log['ActionTaken']}"
        pdf.cell(200, 8, txt=text, ln=1)
        if log['Justification']:
            pdf.cell(200, 8, txt=f"    Reason: {log['Justification']}", ln=1)

    filepath = os.path.join(UPLOAD_DIR, "audit_report.pdf")
    pdf.output(filepath)

    return FileResponse(filepath, media_type="application/pdf", filename="audit_report.pdf")

@app.get("/api/admin/milestones/pending")
def get_pending_milestones(authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Admin':
        raise HTTPException(status_code=403, detail="Unauthorized")
    c = db.cursor()
    c.execute("""
        SELECT m.*, t.Title as TenderTitle, u.Name as ArtistName
        FROM Milestones m
        JOIN Tenders t ON m.TenderID = t.TenderID
        JOIN Users u ON t.AssignedArtistID = u.UserID
        WHERE m.Status = 'Submitted'
    """)
    return [format_row(row) for row in c.fetchall()]

@app.post("/api/admin/milestones/{milestone_id}/approve")
def approve_milestone(milestone_id: int, authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Admin':
        raise HTTPException(status_code=403, detail="Unauthorized")
    admin_id = get_user_id(authorization)
    c = db.cursor()
    c.execute("UPDATE Milestones SET Status = 'Approved' WHERE MilestoneID = %s", (milestone_id,))
    if c.rowcount == 0:
        raise HTTPException(status_code=404, detail="Milestone not found")

    c.execute("SELECT TenderID, PhaseName FROM Milestones WHERE MilestoneID = %s", (milestone_id,))
    m = format_row(c.fetchone())

    c.execute('''INSERT INTO AuditLogs (AdminID, TenderID, ActionTaken, Justification)
                 VALUES (%s, %s, %s, %s)''',
              (admin_id, m['TenderID'], 'APPROVED_MILESTONE', f"Verified Proof of Work for {m['PhaseName']}"))
    db.commit()
    return {"message": "Milestone approved"}

@app.get("/api/artist/{artist_id}/tenders")
def get_artist_tenders(artist_id: int, db: psycopg2.extensions.connection = Depends(get_db)):
    c = db.cursor()
    c.execute("SELECT * FROM Tenders WHERE AssignedArtistID = %s", (artist_id,))
    return [format_row(row) for row in c.fetchall()]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)