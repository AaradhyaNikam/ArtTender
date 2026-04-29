import psycopg2
import psycopg2.extras
import os

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/arttender')

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn

def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    c = conn.cursor()

    # Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS Users (
        UserID SERIAL PRIMARY KEY,
        Name TEXT NOT NULL,
        Role TEXT NOT NULL CHECK(Role IN ('Admin', 'Artist')),
        Email TEXT UNIQUE NOT NULL,
        PasswordHash TEXT NOT NULL,
        ContactInfo TEXT,
        AccountStatus TEXT DEFAULT 'Pending' CHECK(AccountStatus IN ('Pending', 'Active', 'Suspended'))
    )''')

    # Portfolios Table
    c.execute('''CREATE TABLE IF NOT EXISTS Portfolios (
        PortfolioID SERIAL PRIMARY KEY,
        ArtistID INTEGER NOT NULL,
        ImageURL TEXT NOT NULL,
        ArtStyleTags TEXT,
        DateUploaded TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(ArtistID) REFERENCES Users(UserID)
    )''')

    # Tenders Table
    c.execute('''CREATE TABLE IF NOT EXISTS Tenders (
        TenderID SERIAL PRIMARY KEY,
        Title TEXT NOT NULL,
        Description TEXT,
        TotalBudget REAL NOT NULL,
        PlatformCommission REAL NOT NULL,
        PayoutAmount REAL NOT NULL,
        Deadline TIMESTAMP NOT NULL,
        Status TEXT DEFAULT 'Open' CHECK(Status IN ('Open', 'Assigned', 'In Progress', 'Completed')),
        AssignedArtistID INTEGER,
        AdminID INTEGER NOT NULL,
        CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(AssignedArtistID) REFERENCES Users(UserID),
        FOREIGN KEY(AdminID) REFERENCES Users(UserID)
    )''')

    # Applications Table
    c.execute('''CREATE TABLE IF NOT EXISTS Applications (
        ApplicationID SERIAL PRIMARY KEY,
        TenderID INTEGER NOT NULL,
        ArtistID INTEGER NOT NULL,
        AppliedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(TenderID, ArtistID),
        FOREIGN KEY(TenderID) REFERENCES Tenders(TenderID),
        FOREIGN KEY(ArtistID) REFERENCES Users(UserID)
    )''')

    # Milestones Table
    c.execute('''CREATE TABLE IF NOT EXISTS Milestones (
        MilestoneID SERIAL PRIMARY KEY,
        TenderID INTEGER NOT NULL,
        PhaseName TEXT NOT NULL,
        Status TEXT DEFAULT 'Pending' CHECK(Status IN ('Pending', 'Submitted', 'Approved', 'Rejected')),
        ProofImageURL TEXT,
        GeoTagData TEXT,
        FOREIGN KEY(TenderID) REFERENCES Tenders(TenderID)
    )''')

    # Performance Table
    c.execute('''CREATE TABLE IF NOT EXISTS Performance (
        RatingID SERIAL PRIMARY KEY,
        ArtistID INTEGER NOT NULL,
        TenderID INTEGER,
        QualityScore INTEGER CHECK(QualityScore BETWEEN 1 AND 100),
        CapacityTag TEXT,
        FOREIGN KEY(ArtistID) REFERENCES Users(UserID),
        FOREIGN KEY(TenderID) REFERENCES Tenders(TenderID)
    )''')

    # AuditLogs Table - APPEND ONLY
    c.execute('''CREATE TABLE IF NOT EXISTS AuditLogs (
        LogID SERIAL PRIMARY KEY,
        Timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        AdminID INTEGER NOT NULL,
        TenderID INTEGER,
        ActionTaken TEXT NOT NULL,
        Justification TEXT,
        FOREIGN KEY(AdminID) REFERENCES Users(UserID),
        FOREIGN KEY(TenderID) REFERENCES Tenders(TenderID)
    )''')

    # Triggers for immutability
    c.execute('''
    CREATE OR REPLACE FUNCTION prevent_audit_modifications()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'Updates and deletions to AuditLogs are strictly prohibited.';
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    ''')
            
    c.execute('''
    DROP TRIGGER IF EXISTS prevent_audit_update ON AuditLogs;
    CREATE TRIGGER prevent_audit_update
    BEFORE UPDATE ON AuditLogs
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modifications();
    ''')

    c.execute('''
    DROP TRIGGER IF EXISTS prevent_audit_delete ON AuditLogs;
    CREATE TRIGGER prevent_audit_delete
    BEFORE DELETE ON AuditLogs
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modifications();
    ''')

    # Seed Admin
    c.execute("SELECT * FROM Users WHERE Email = 'admin@arttender.com'")
    if not c.fetchone():
        c.execute('''INSERT INTO Users (Name, Role, Email, PasswordHash, AccountStatus) 
                     VALUES (%s, %s, %s, %s, %s)''',
                  ('Super Admin', 'Admin', 'admin@arttender.com', 'admin123', 'Active'))
        
    # Seed dummy Artists
    c.execute("SELECT count(*) as count FROM Users WHERE Role = 'Artist'")
    count = c.fetchone()[0]
    if count == 0:
        c.execute('''INSERT INTO Users (Name, Role, Email, PasswordHash, AccountStatus) 
                     VALUES (%s, %s, %s, %s, %s) RETURNING UserID''',
                  ('Jane Doe (Sculpture)', 'Artist', 'jane@artist.com', 'artist123', 'Active'))
        artist1_id = c.fetchone()[0]
        c.execute('INSERT INTO Performance (ArtistID, QualityScore, CapacityTag) VALUES (%s, %s, %s)', (artist1_id, 95, 'High Capacity'))
        c.execute('INSERT INTO Portfolios (ArtistID, ImageURL, ArtStyleTags) VALUES (%s, %s, %s)', (artist1_id, '/uploads/dummy1.jpg', 'Modern, Sculpture, Metal'))

        c.execute('''INSERT INTO Users (Name, Role, Email, PasswordHash, AccountStatus) 
                     VALUES (%s, %s, %s, %s, %s) RETURNING UserID''',
                  ('John Smith (Mural)', 'Artist', 'john@artist.com', 'artist123', 'Active'))
        artist2_id = c.fetchone()[0]
        c.execute('INSERT INTO Performance (ArtistID, QualityScore, CapacityTag) VALUES (%s, %s, %s)', (artist2_id, 88, 'Medium Capacity'))
        c.execute('INSERT INTO Portfolios (ArtistID, ImageURL, ArtStyleTags) VALUES (%s, %s, %s)', (artist2_id, '/uploads/dummy2.jpg', 'Mural, Spray, Street Art'))
        
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
