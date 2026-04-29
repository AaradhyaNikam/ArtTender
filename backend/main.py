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

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

# FIX 1: Serve frontend index.html at root "/"
@app.get("/")
def serve_index():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    return FileResponse(index_path)

def save_upload_file(upload_file: UploadFile) -> str:
    if not upload_file:
        return ""
    filename = f"{uuid.uuid4()}_{upload_file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return f"/uploads/{filename}"

# FIX 2: init_db() called after all setup, before routes that need DB
database.init_db()

def get_db():
    conn = database.get_db_connection()
    try:
        yield conn
    finally:
        conn.close()

# FIX 3: Helper to extract role safely from token
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

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/auth/login")
def login(req: LoginRequest, db: psycopg2.extensions.connection = Depends(get_db)):
    c = db.cursor()
    # FIX 4: Fetch PasswordHash separately, then verify with bcrypt
    c.execute("SELECT UserID, Name, Role, AccountStatus, PasswordHash FROM Users WHERE Email = %s", (req.email,))
    user = c.fetchone()
    if user:
        # Check bcrypt hash; fallback to plain text for legacy seeds
        try:
            password_valid = bcrypt.checkpw(req.password.encode('utf-8'), user['passwordhash'].encode('utf-8'))
        except Exception:
            password_valid = (req.password == user['passwordhash'])

        if not password_valid:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if user['accountstatus'] != 'Active':
            raise HTTPException(status_code=403, detail="Account is pending or suspended.")

        return {
            "token": f"{user['userid']}_{user['role']}",
            "user": {
                "UserID": user['userid'],
                "Name": user['name'],
                "Role": user['role'],
                "AccountStatus": user['accountstatus']
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

    # FIX 5: Hash password with bcrypt before storing
    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    c.execute('''INSERT INTO Users (Name, Role, Email, PasswordHash, ContactInfo, AccountStatus)
                 VALUES (%s, %s, %s, %s, %s, %s) RETURNING UserID''',
              (name, 'Artist', email, hashed_pw, contact_info, 'Active'))
    user_id = c.fetchone()['userid']

    c.execute('INSERT INTO Portfolios (ArtistID, ImageURL, ArtStyleTags) VALUES (%s, %s, %s)', (user_id, image_url, art_style_tags))
    c.execute('INSERT INTO Performance (ArtistID, QualityScore, CapacityTag) VALUES (%s, %s, %s)', (user_id, 70, 'Available'))

    db.commit()
    return {"message": "Signup successful. Your account is active."}

@app.get("/api/admin/users/pending")
def get_pending_users(authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    # FIX 6: Proper role check using helper
    if not authorization or get_role(authorization) != 'Admin':
        raise HTTPException(status_code=403, detail="Unauthorized")
    c = db.cursor()
    c.execute("SELECT UserID, Name, Email, ContactInfo, AccountStatus FROM Users WHERE AccountStatus = 'Pending'")
    return [dict(row) for row in c.fetchall()]

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
    return [dict(row) for row in c.fetchall()]

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
    c.execute("SELECT * FROM Tenders ORDER BY CreatedAt DESC")
    return [dict(row) for row in c.fetchall()]

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
    tender_id = c.fetchone()['tenderid']

    c.execute('''INSERT INTO AuditLogs (AdminID, TenderID, ActionTaken, Justification)
                 VALUES (%s, %s, %s, %s)''',
              (admin_id, tender_id, 'CREATED_TENDER', 'New tender created'))
    db.commit()
    return {"message": "Tender created successfully", "TenderID": tender_id}

# FIX 7: Moved /api/tenders/open BEFORE /api/tenders/{tender_id}/... routes
# so FastAPI doesn't treat "open" as a tender_id integer
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
    return [dict(row) for row in c.fetchall()]

@app.post("/api/tenders/{tender_id}/apply")
def apply_tender(tender_id: int, authorization: str = Header(None), db: psycopg2.extensions.connection = Depends(get_db)):
    if not authorization or get_role(authorization) != 'Artist':
        raise HTTPException(status_code=403, detail="Unauthorized")
    artist_id = get_user_id(authorization)

    c = db.cursor()
    c.execute("SELECT Status, Deadline FROM Tenders WHERE TenderID = %s", (tender_id,))
    tender = c.fetchone()

    if not tender or tender['status'] != 'Open':
        raise HTTPException(status_code=400, detail="Tender is not available.")

    if tender['deadline'] < datetime.now().isoformat():
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
    tender = c.fetchone()
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    tender_desc = tender['description'].lower() if tender['description'] else ""
    tender_keywords = set(re.findall(r'\b\w+\b', tender_desc))

    c.execute('''
        SELECT u.UserID, u.Name, p.QualityScore, p.CapacityTag, port.ArtStyleTags, port.ImageURL
        FROM Users u
        JOIN Applications a ON u.UserID = a.ArtistID
        LEFT JOIN Performance p ON u.UserID = p.ArtistID
        LEFT JOIN Portfolios port ON u.UserID = port.ArtistID
        WHERE u.Role = 'Artist' AND u.AccountStatus = 'Active' AND a.TenderID = %s
    ''', (tender_id,))
    all_artists = [dict(row) for row in c.fetchall()]

    scored_candidates = []
    for artist in all_artists:
        tags = artist['artstyletags'] or ""
        artist_tags = set(re.findall(r'\b\w+\b', tags.lower()))

        match_count = len(tender_keywords.intersection(artist_tags))
        ai_score = (match_count * 100) + (artist['qualityscore'] or 0)

        artist['qualityscore'] = ai_score
        scored_candidates.append(artist)

    scored_candidates.sort(key=lambda x: x['qualityscore'], reverse=True)
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
    tender = c.fetchone()
    if not tender or tender['status'] != 'Open':
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
    return [dict(row) for row in c.fetchall()]

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
    return [dict(row) for row in c.fetchall()]

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
    logs = [dict(row) for row in c.fetchall()]

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(200, 10, txt="Artiverse - Immutable Audit Ledger Report", ln=1, align='C')
    pdf.ln(10)

    pdf.set_font("helvetica", size=10)
    for log in logs:
        text = f"[{log['timestamp']}] Admin: {log['adminname']} | Tender: {log['tenderid']} | Action: {log['actiontaken']}"
        pdf.cell(200, 8, txt=text, ln=1)
        if log['justification']:
            pdf.cell(200, 8, txt=f"    Reason: {log['justification']}", ln=1)

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
    return [dict(row) for row in c.fetchall()]

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
    m = c.fetchone()

    c.execute('''INSERT INTO AuditLogs (AdminID, TenderID, ActionTaken, Justification)
                 VALUES (%s, %s, %s, %s)''',
              (admin_id, m['tenderid'], 'APPROVED_MILESTONE', f"Verified Proof of Work for {m['phasename']}"))
    db.commit()
    return {"message": "Milestone approved"}

@app.get("/api/artist/{artist_id}/tenders")
def get_artist_tenders(artist_id: int, db: psycopg2.extensions.connection = Depends(get_db)):
    c = db.cursor()
    c.execute("SELECT * FROM Tenders WHERE AssignedArtistID = %s", (artist_id,))
    return [dict(row) for row in c.fetchall()]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
