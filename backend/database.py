import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'arttender.db')

def get_db_connection():
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    # Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS Users (
        UserID INTEGER PRIMARY KEY AUTOINCREMENT,
        Name TEXT NOT NULL,
        Role TEXT NOT NULL CHECK(Role IN ('Admin', 'Artist')),
        Email TEXT UNIQUE NOT NULL,
        PasswordHash TEXT NOT NULL,
        ContactInfo TEXT,
        AccountStatus TEXT DEFAULT 'Pending' CHECK(AccountStatus IN ('Pending', 'Active', 'Suspended'))
    )''')

    # Portfolios Table
    c.execute('''CREATE TABLE IF NOT EXISTS Portfolios (
        PortfolioID INTEGER PRIMARY KEY AUTOINCREMENT,
        ArtistID INTEGER NOT NULL,
        ImageURL TEXT NOT NULL,
        ArtStyleTags TEXT,
        DateUploaded DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(ArtistID) REFERENCES Users(UserID)
    )''')

    # Tenders Table
    c.execute('''CREATE TABLE IF NOT EXISTS Tenders (
        TenderID INTEGER PRIMARY KEY AUTOINCREMENT,
        Title TEXT NOT NULL,
        Description TEXT,
        TotalBudget REAL NOT NULL,
        PlatformCommission REAL NOT NULL,
        PayoutAmount REAL NOT NULL,
        Deadline DATETIME NOT NULL,
        Status TEXT DEFAULT 'Open' CHECK(Status IN ('Open', 'Assigned', 'In Progress', 'Completed')),
        AssignedArtistID INTEGER,
        AdminID INTEGER NOT NULL,
        CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(AssignedArtistID) REFERENCES Users(UserID),
        FOREIGN KEY(AdminID) REFERENCES Users(UserID)
    )''')

    # Applications Table
    c.execute('''CREATE TABLE IF NOT EXISTS Applications (
        ApplicationID INTEGER PRIMARY KEY AUTOINCREMENT,
        TenderID INTEGER NOT NULL,
        ArtistID INTEGER NOT NULL,
        AppliedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(TenderID, ArtistID),
        FOREIGN KEY(TenderID) REFERENCES Tenders(TenderID),
        FOREIGN KEY(ArtistID) REFERENCES Users(UserID)
    )''')

    # Milestones Table
    c.execute('''CREATE TABLE IF NOT EXISTS Milestones (
        MilestoneID INTEGER PRIMARY KEY AUTOINCREMENT,
        TenderID INTEGER NOT NULL,
        PhaseName TEXT NOT NULL,
        Status TEXT DEFAULT 'Pending' CHECK(Status IN ('Pending', 'Submitted', 'Approved', 'Rejected')),
        ProofImageURL TEXT,
        GeoTagData TEXT,
        FOREIGN KEY(TenderID) REFERENCES Tenders(TenderID)
    )''')

    # Performance Table
    c.execute('''CREATE TABLE IF NOT EXISTS Performance (
        RatingID INTEGER PRIMARY KEY AUTOINCREMENT,
        ArtistID INTEGER NOT NULL,
        TenderID INTEGER,
        QualityScore INTEGER CHECK(QualityScore BETWEEN 1 AND 100),
        CapacityTag TEXT,
        FOREIGN KEY(ArtistID) REFERENCES Users(UserID),
        FOREIGN KEY(TenderID) REFERENCES Tenders(TenderID)
    )''')

    # AuditLogs Table - APPEND ONLY
    c.execute('''CREATE TABLE IF NOT EXISTS AuditLogs (
        LogID INTEGER PRIMARY KEY AUTOINCREMENT,
        Timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        AdminID INTEGER NOT NULL,
        TenderID INTEGER,
        ActionTaken TEXT NOT NULL,
        Justification TEXT,
        FOREIGN KEY(AdminID) REFERENCES Users(UserID),
        FOREIGN KEY(TenderID) REFERENCES Tenders(TenderID)
    )''')

    # Triggers for immutability
    c.execute('''CREATE TRIGGER IF NOT EXISTS prevent_audit_update
            BEFORE UPDATE ON AuditLogs
            BEGIN
                SELECT RAISE(ABORT, 'Updates to AuditLogs are strictly prohibited.');
            END;''')
            
    c.execute('''CREATE TRIGGER IF NOT EXISTS prevent_audit_delete
            BEFORE DELETE ON AuditLogs
            BEGIN
                SELECT RAISE(ABORT, 'Deletions from AuditLogs are strictly prohibited.');
            END;''')

    # Seed Admin
    c.execute('SELECT * FROM Users WHERE Email = "admin@arttender.com"')
    if not c.fetchone():
        # Hash for 'admin123' (simplified for demonstration without bcrypt dependency)
        c.execute('''INSERT INTO Users (Name, Role, Email, PasswordHash, AccountStatus) 
                     VALUES (?, ?, ?, ?, ?)''',
                  ('Super Admin', 'Admin', 'admin@arttender.com', 'admin123', 'Active'))
        
    # Seed dummy Artists
    c.execute('SELECT count(*) as count FROM Users WHERE Role = "Artist"')
    count = c.fetchone()['count']
    if count == 0:
        c.execute('''INSERT INTO Users (Name, Role, Email, PasswordHash, AccountStatus) 
                     VALUES (?, ?, ?, ?, ?)''',
                  ('Jane Doe (Sculpture)', 'Artist', 'jane@artist.com', 'artist123', 'Active'))
        artist1_id = c.lastrowid
        c.execute('INSERT INTO Performance (ArtistID, QualityScore, CapacityTag) VALUES (?, ?, ?)', (artist1_id, 95, 'High Capacity'))
        c.execute('INSERT INTO Portfolios (ArtistID, ImageURL, ArtStyleTags) VALUES (?, ?, ?)', (artist1_id, '/uploads/dummy1.jpg', 'Modern, Sculpture, Metal'))

        c.execute('''INSERT INTO Users (Name, Role, Email, PasswordHash, AccountStatus) 
                     VALUES (?, ?, ?, ?, ?)''',
                  ('John Smith (Mural)', 'Artist', 'john@artist.com', 'artist123', 'Active'))
        artist2_id = c.lastrowid
        c.execute('INSERT INTO Performance (ArtistID, QualityScore, CapacityTag) VALUES (?, ?, ?)', (artist2_id, 88, 'Medium Capacity'))
        c.execute('INSERT INTO Portfolios (ArtistID, ImageURL, ArtStyleTags) VALUES (?, ?, ?)', (artist2_id, '/uploads/dummy2.jpg', 'Mural, Spray, Street Art'))
        
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
