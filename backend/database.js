const sqlite3 = require('sqlite3').verbose();
const path = require('path');

const dbPath = path.resolve(__dirname, 'arttender.db');
const db = new sqlite3.Database(dbPath, (err) => {
    if (err) {
        console.error('Error connecting to database:', err.message);
    } else {
        console.log('Connected to SQLite database.');
        initDB();
    }
});

function initDB() {
    db.serialize(() => {
        // Users Table
        db.run(`CREATE TABLE IF NOT EXISTS Users (
            UserID INTEGER PRIMARY KEY AUTOINCREMENT,
            Name TEXT NOT NULL,
            Role TEXT NOT NULL CHECK(Role IN ('Admin', 'Artist')),
            Email TEXT UNIQUE NOT NULL,
            PasswordHash TEXT NOT NULL,
            ContactInfo TEXT,
            AccountStatus TEXT DEFAULT 'Pending' CHECK(AccountStatus IN ('Pending', 'Active', 'Suspended'))
        )`);

        // Portfolios Table
        db.run(`CREATE TABLE IF NOT EXISTS Portfolios (
            PortfolioID INTEGER PRIMARY KEY AUTOINCREMENT,
            ArtistID INTEGER NOT NULL,
            ImageURL TEXT NOT NULL,
            ArtStyleTags TEXT,
            DateUploaded DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(ArtistID) REFERENCES Users(UserID)
        )`);

        // Tenders Table
        db.run(`CREATE TABLE IF NOT EXISTS Tenders (
            TenderID INTEGER PRIMARY KEY AUTOINCREMENT,
            Title TEXT NOT NULL,
            Description TEXT,
            TotalBudget REAL NOT NULL,
            PlatformCommission REAL NOT NULL,
            PayoutAmount REAL NOT NULL,
            Status TEXT DEFAULT 'Open' CHECK(Status IN ('Open', 'Assigned', 'In Progress', 'Completed')),
            AssignedArtistID INTEGER,
            AdminID INTEGER NOT NULL,
            CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(AssignedArtistID) REFERENCES Users(UserID),
            FOREIGN KEY(AdminID) REFERENCES Users(UserID)
        )`);

        // Milestones Table
        db.run(`CREATE TABLE IF NOT EXISTS Milestones (
            MilestoneID INTEGER PRIMARY KEY AUTOINCREMENT,
            TenderID INTEGER NOT NULL,
            PhaseName TEXT NOT NULL,
            Status TEXT DEFAULT 'Pending' CHECK(Status IN ('Pending', 'Submitted', 'Approved', 'Rejected')),
            ProofImageURL TEXT,
            GeoTagData TEXT,
            FOREIGN KEY(TenderID) REFERENCES Tenders(TenderID)
        )`);

        // Performance Table
        db.run(`CREATE TABLE IF NOT EXISTS Performance (
            RatingID INTEGER PRIMARY KEY AUTOINCREMENT,
            ArtistID INTEGER NOT NULL,
            TenderID INTEGER,
            QualityScore INTEGER CHECK(QualityScore BETWEEN 1 AND 100),
            CapacityTag TEXT,
            FOREIGN KEY(ArtistID) REFERENCES Users(UserID),
            FOREIGN KEY(TenderID) REFERENCES Tenders(TenderID)
        )`);

        // AuditLogs Table - APPEND ONLY (No UPDATE/DELETE)
        db.run(`CREATE TABLE IF NOT EXISTS AuditLogs (
            LogID INTEGER PRIMARY KEY AUTOINCREMENT,
            Timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            AdminID INTEGER NOT NULL,
            TenderID INTEGER,
            ActionTaken TEXT NOT NULL,
            Justification TEXT,
            FOREIGN KEY(AdminID) REFERENCES Users(UserID),
            FOREIGN KEY(TenderID) REFERENCES Tenders(TenderID)
        )`);

        // Prevent UPDATE/DELETE on AuditLogs via Triggers
        db.run(`CREATE TRIGGER IF NOT EXISTS prevent_audit_update
                BEFORE UPDATE ON AuditLogs
                BEGIN
                    SELECT RAISE(ABORT, 'Updates to AuditLogs are strictly prohibited.');
                END;`);

        db.run(`CREATE TRIGGER IF NOT EXISTS prevent_audit_delete
                BEFORE DELETE ON AuditLogs
                BEGIN
                    SELECT RAISE(ABORT, 'Deletions from AuditLogs are strictly prohibited.');
                END;`);

        // Seed Admin user if not exists
        db.get(`SELECT * FROM Users WHERE Email = 'admin@arttender.com'`, (err, row) => {
            if (!row) {
                const bcrypt = require('bcrypt');
                const hash = bcrypt.hashSync('admin123', 10);
                db.run(`INSERT INTO Users (Name, Role, Email, PasswordHash, AccountStatus) VALUES (?, ?, ?, ?, ?)`,
                    ['Super Admin', 'Admin', 'admin@arttender.com', hash, 'Active']);
                console.log('Seeded initial admin user (admin@arttender.com / admin123)');
            }
        });
        
        // Seed dummy artists for testing if no artists exist
        db.get(`SELECT count(*) as count FROM Users WHERE Role = 'Artist'`, (err, row) => {
            if (row && row.count === 0) {
                 const bcrypt = require('bcrypt');
                 const hash = bcrypt.hashSync('artist123', 10);
                 
                 // Artist 1
                 db.run(`INSERT INTO Users (Name, Role, Email, PasswordHash, AccountStatus) VALUES (?, ?, ?, ?, ?)`,
                    ['Jane Doe (Sculpture)', 'Artist', 'jane@artist.com', hash, 'Active'], function(err) {
                        if (!err) {
                            const artistId = this.lastID;
                            db.run(`INSERT INTO Performance (ArtistID, QualityScore, CapacityTag) VALUES (?, ?, ?)`, [artistId, 95, 'High Capacity']);
                            db.run(`INSERT INTO Portfolios (ArtistID, ImageURL, ArtStyleTags) VALUES (?, ?, ?)`, [artistId, '/uploads/dummy1.jpg', 'Modern, Sculpture, Metal']);
                        }
                    });
                 
                 // Artist 2
                 db.run(`INSERT INTO Users (Name, Role, Email, PasswordHash, AccountStatus) VALUES (?, ?, ?, ?, ?)`,
                    ['John Smith (Mural)', 'Artist', 'john@artist.com', hash, 'Active'], function(err) {
                        if (!err) {
                            const artistId = this.lastID;
                            db.run(`INSERT INTO Performance (ArtistID, QualityScore, CapacityTag) VALUES (?, ?, ?)`, [artistId, 88, 'Medium Capacity']);
                            db.run(`INSERT INTO Portfolios (ArtistID, ImageURL, ArtStyleTags) VALUES (?, ?, ?)`, [artistId, '/uploads/dummy2.jpg', 'Mural, Spray, Street Art']);
                        }
                    });

                 // Artist 3
                 db.run(`INSERT INTO Users (Name, Role, Email, PasswordHash, AccountStatus) VALUES (?, ?, ?, ?, ?)`,
                    ['Alice Johnson (Digital/Light)', 'Artist', 'alice@artist.com', hash, 'Active'], function(err) {
                         if (!err) {
                             const artistId = this.lastID;
                             db.run(`INSERT INTO Performance (ArtistID, QualityScore, CapacityTag) VALUES (?, ?, ?)`, [artistId, 92, 'Available']);
                             db.run(`INSERT INTO Portfolios (ArtistID, ImageURL, ArtStyleTags) VALUES (?, ?, ?)`, [artistId, '/uploads/dummy3.jpg', 'Digital, Light Installation']);
                         }
                    });
                 console.log('Seeded initial dummy artists');
            }
        });
    });
}

module.exports = db;
