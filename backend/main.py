from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import database
import sqlite3
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

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/auth/login")
def login(req: LoginRequest, db: sqlite3.Connection = Depends(get_db)):
    c = db.cursor()
    c.execute("SELECT UserID, Name, Role, AccountStatus FROM Users WHERE Email = ? AND PasswordHash = ?", (req.email, req.password))
    user = c.fetchone()
    if user:
        if user['AccountStatus'] != 'Active':
            raise HTTPException(status_code=403, detail="Account is pending or suspended.")
        return {"token": f"{user['UserID']}_{user['Role']}", "user": dict(user)}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/api/auth/signup")
def signup(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    contact_info: str = Form(None),
    art_style_tags: str = Form(None),
    portfolio_image: UploadFile = File(...),
    db: sqlite3.Connection = Depends(get_db)
):
    c = db.cursor()
    c.execute("SELECT UserID FROM Users WHERE Email = ?", (email,))
    if c.fetchone():
        raise HTTPException(status_code=400, detail="Email already registered")
        
    image_url = save_upload_file(portfolio_image)
    
    c.execute('''INSERT INTO Users (Name, Role, Email, PasswordHash, ContactInfo, AccountStatus) 
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (name, 'Artist', email, password, contact_info, 'Active'))
    user_id = c.lastrowid
    
    c.execute('INSERT INTO Portfolios (ArtistID, ImageURL, ArtStyleTags) VALUES (?, ?, ?)', (user_id, image_url, art_style_tags))
    c.execute('INSERT INTO Performance (ArtistID, QualityScore, CapacityTag) VALUES (?, ?, ?)', (user_id, 70, 'Available'))
    
    db.commit()
    return {"message": "Signup successful. Your account is active."}

@app.get("/api/admin/users/pending")
def get_pending_users(authorization: str = Header(None), db: sqlite3.Connection = Depends(get_db)):
    if not authorization or 'Admin' not in authorization:
        raise HTTPException(status_code=403, detail="Unauthorized")
    c = db.cursor()
    c.execute("SELECT UserID, Name, Email, ContactInfo, AccountStatus FROM Users WHERE AccountStatus = 'Pending'")
    return [dict(row) for row in c.fetchall()]

@app.get("/api/admin/users")
def get_all_users(authorization: str = Header(None), db: sqlite3.Connection = Depends(get_db)):
    if not authorization or 'Admin' not in authorization:
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
def approve_user(user_id: int, authorization: str = Header(None), db: sqlite3.Connection = Depends(get_db)):
    if not authorization or 'Admin' not in authorization:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    c = db.cursor()
    c.execute("UPDATE Users SET AccountStatus = 'Active' WHERE UserID = ?", (user_id,))
    if c.rowcount == 0:
        raise HTTPException(status_code=404, detail="User not found")
        
    db.commit()
    return {"message": "User approved"}

@app.get("/api/tenders")
def get_tenders(db: sqlite3.Connection = Depends(get_db)):
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
def create_tender(req: TenderCreate, authorization: str = Header(None), db: sqlite3.Connection = Depends(get_db)):
    if not authorization or 'Admin' not in authorization:
        raise HTTPException(status_code=403, detail="Unauthorized")
    admin_id = int(authorization.split('_')[0])
    
    payout = req.total_budget - (req.total_budget * (req.platform_commission / 100))
    
    c = db.cursor()
    c.execute('''INSERT INTO Tenders (Title, Description, TotalBudget, PlatformCommission, PayoutAmount, Deadline, AdminID)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (req.title, req.description, req.total_budget, req.platform_commission, payout, req.deadline, admin_id))
    tender_id = c.lastrowid
    
    c.execute('''INSERT INTO AuditLogs (AdminID, TenderID, ActionTaken, Justification)
                 VALUES (?, ?, ?, ?)''',
              (admin_id, tender_id, 'CREATED_TENDER', 'New tender created'))
    db.commit()
    return {"message": "Tender created successfully", "TenderID": tender_id}

@app.get("/api/tenders/open")
def get_open_tenders(authorization: str = Header(None), db: sqlite3.Connection = Depends(get_db)):
    if not authorization or 'Artist' not in authorization:
        raise HTTPException(status_code=403, detail="Unauthorized")
    artist_id = int(authorization.split('_')[0])
    c = db.cursor()
    
    current_time = datetime.now().isoformat()
    # Return tenders where deadline is in future, and the artist hasn't applied yet
    c.execute("""
        SELECT t.* FROM Tenders t
        WHERE t.Status = 'Open' 
        AND t.Deadline > ?
        AND t.TenderID NOT IN (SELECT TenderID FROM Applications WHERE ArtistID = ?)
        ORDER BY t.Deadline ASC
    """, (current_time, artist_id,))
    return [dict(row) for row in c.fetchall()]

@app.post("/api/tenders/{tender_id}/apply")
def apply_tender(tender_id: int, authorization: str = Header(None), db: sqlite3.Connection = Depends(get_db)):
    if not authorization or 'Artist' not in authorization:
        raise HTTPException(status_code=403, detail="Unauthorized")
    artist_id = int(authorization.split('_')[0])
    
    c = db.cursor()
    c.execute("SELECT Status, Deadline FROM Tenders WHERE TenderID = ?", (tender_id,))
    tender = c.fetchone()
    
    if not tender or tender['Status'] != 'Open':
        raise HTTPException(status_code=400, detail="Tender is not available.")
    
    # Check if deadline passed
    if tender['Deadline'] < datetime.now().isoformat():
        raise HTTPException(status_code=400, detail="Deadline has passed.")
        
    try:
        c.execute("INSERT INTO Applications (TenderID, ArtistID) VALUES (?, ?)", (tender_id, artist_id))
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Already applied.")
        
    return {"message": "Successfully applied for the tender."}

@app.get("/api/tenders/{tender_id}/candidates")
def get_candidates(tender_id: int, db: sqlite3.Connection = Depends(get_db)):
    c = db.cursor()
    
    c.execute("SELECT Description, Deadline FROM Tenders WHERE TenderID = ?", (tender_id,))
    tender = c.fetchone()
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
        
    tender_desc = tender['Description'].lower() if tender['Description'] else ""
    tender_keywords = set(re.findall(r'\b\w+\b', tender_desc))
    
    # ONLY GET ARTISTS WHO APPLIED
    c.execute('''
        SELECT u.UserID, u.Name, p.QualityScore, p.CapacityTag, port.ArtStyleTags, port.ImageURL
        FROM Users u
        JOIN Applications a ON u.UserID = a.ArtistID
        LEFT JOIN Performance p ON u.UserID = p.ArtistID
        LEFT JOIN Portfolios port ON u.UserID = port.ArtistID
        WHERE u.Role = 'Artist' AND u.AccountStatus = 'Active' AND a.TenderID = ?
    ''', (tender_id,))
    all_artists = [dict(row) for row in c.fetchall()]
    
    scored_candidates = []
    for artist in all_artists:
        tags = artist['ArtStyleTags'] or ""
        artist_tags = set(re.findall(r'\b\w+\b', tags.lower()))
        
        match_count = len(tender_keywords.intersection(artist_tags))
        ai_score = (match_count * 100) + (artist['QualityScore'] or 0)
        
        artist['QualityScore'] = ai_score # Override score for display purposes
        scored_candidates.append(artist)
        
    scored_candidates.sort(key=lambda x: x['QualityScore'], reverse=True)
    return scored_candidates[:5]

class AwardRequest(BaseModel):
    artist_id: int
    justification: str

@app.post("/api/tenders/{tender_id}/award")
def award_tender(tender_id: int, req: AwardRequest, authorization: str = Header(None), db: sqlite3.Connection = Depends(get_db)):
    if not authorization or 'Admin' not in authorization:
        raise HTTPException(status_code=403, detail="Unauthorized")
    admin_id = int(authorization.split('_')[0])
    
    c = db.cursor()
    c.execute("SELECT Status FROM Tenders WHERE TenderID = ?", (tender_id,))
    tender = c.fetchone()
    if not tender or tender['Status'] != 'Open':
        raise HTTPException(status_code=400, detail="Tender is not open")
        
    c.execute("UPDATE Tenders SET Status = 'Assigned', AssignedArtistID = ? WHERE TenderID = ?", (req.artist_id, tender_id))
    
    c.execute('''INSERT INTO AuditLogs (AdminID, TenderID, ActionTaken, Justification)
                 VALUES (?, ?, ?, ?)''',
              (admin_id, tender_id, 'AWARDED_CONTRACT', req.justification))
              
    c.execute('''INSERT INTO Milestones (TenderID, PhaseName) VALUES (?, ?)''', (tender_id, '25% Upfront Verification'))
    db.commit()
    return {"message": "Contract awarded successfully"}

@app.get("/api/tenders/{tender_id}/milestones")
def get_tender_milestones(tender_id: int, db: sqlite3.Connection = Depends(get_db)):
    c = db.cursor()
    c.execute("SELECT * FROM Milestones WHERE TenderID = ?", (tender_id,))
    return [dict(row) for row in c.fetchall()]

@app.post("/api/milestones/{milestone_id}/submit")
def submit_milestone(
    milestone_id: int,
    geo_tag_data: str = Form(...),
    proof_image: UploadFile = File(...),
    authorization: str = Header(None),
    db: sqlite3.Connection = Depends(get_db)
):
    if not authorization or 'Artist' not in authorization:
        raise HTTPException(status_code=403, detail="Unauthorized")
        
    image_url = save_upload_file(proof_image)
    
    c = db.cursor()
    c.execute("UPDATE Milestones SET Status = 'Submitted', ProofImageURL = ?, GeoTagData = ? WHERE MilestoneID = ?", 
              (image_url, geo_tag_data, milestone_id))
              
    if c.rowcount == 0:
        raise HTTPException(status_code=404, detail="Milestone not found")
        
    db.commit()
    return {"message": "Milestone submitted successfully"}

@app.get("/api/auditlogs")
def get_audit_logs(authorization: str = Header(None), db: sqlite3.Connection = Depends(get_db)):
    if not authorization or 'Admin' not in authorization:
        raise HTTPException(status_code=403, detail="Unauthorized")
    c = db.cursor()
    c.execute("SELECT * FROM AuditLogs ORDER BY Timestamp DESC")
    return [dict(row) for row in c.fetchall()]

@app.get("/api/auditlogs/export")
def export_audit_logs(authorization: str = Header(None), db: sqlite3.Connection = Depends(get_db)):
    if not authorization or 'Admin' not in authorization:
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
        text = f"[{log['Timestamp']}] Admin: {log['AdminName']} | Tender: {log['TenderID']} | Action: {log['ActionTaken']}"
        pdf.cell(200, 8, txt=text, ln=1)
        if log['Justification']:
            pdf.cell(200, 8, txt=f"    Reason: {log['Justification']}", ln=1)
            
    filepath = os.path.join(UPLOAD_DIR, "audit_report.pdf")
    pdf.output(filepath)
    
    return FileResponse(filepath, media_type="application/pdf", filename="audit_report.pdf")

@app.get("/api/admin/milestones/pending")
def get_pending_milestones(authorization: str = Header(None), db: sqlite3.Connection = Depends(get_db)):
    if not authorization or 'Admin' not in authorization:
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
def approve_milestone(milestone_id: int, authorization: str = Header(None), db: sqlite3.Connection = Depends(get_db)):
    if not authorization or 'Admin' not in authorization:
        raise HTTPException(status_code=403, detail="Unauthorized")
    admin_id = int(authorization.split('_')[0])
    c = db.cursor()
    c.execute("UPDATE Milestones SET Status = 'Approved' WHERE MilestoneID = ?", (milestone_id,))
    if c.rowcount == 0:
        raise HTTPException(status_code=404, detail="Milestone not found")
        
    c.execute("SELECT TenderID, PhaseName FROM Milestones WHERE MilestoneID = ?", (milestone_id,))
    m = c.fetchone()
    
    c.execute('''INSERT INTO AuditLogs (AdminID, TenderID, ActionTaken, Justification)
                 VALUES (?, ?, ?, ?)''',
              (admin_id, m['TenderID'], 'APPROVED_MILESTONE', f"Verified Proof of Work for {m['PhaseName']}"))
    db.commit()
    return {"message": "Milestone approved"}

@app.get("/api/artist/{artist_id}/tenders")
def get_artist_tenders(artist_id: int, db: sqlite3.Connection = Depends(get_db)):
    c = db.cursor()
    c.execute("SELECT * FROM Tenders WHERE AssignedArtistID = ?", (artist_id,))
    return [dict(row) for row in c.fetchall()]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
