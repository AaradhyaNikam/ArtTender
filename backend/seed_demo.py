import psycopg2
import os
from datetime import datetime, timedelta

def seed():
    import database
    database.init_db()
    
    conn = psycopg2.connect(database.DATABASE_URL)
    c = conn.cursor()
    
    c.execute("DELETE FROM Users WHERE Role = 'Artist'")
    c.execute("DELETE FROM Portfolios")
    c.execute("DELETE FROM Performance")
    
    artists = [
        ("Alice Adams", "Metal, Sculpture, Modern", 95),
        ("Bob Brown", "Mural, Street Art, Spray", 88),
        ("Charlie Clark", "Digital, Cyberpunk", 75),
        ("Diana Davis", "Watercolor, Landscape", 82),
        ("Eve Evans", "Abstract, Geometry, Metal", 91),
        ("Frank Ford", "Bronze, Sculpture, Classic", 85),
        ("Grace Green", "Photography, Portrait", 78),
        ("Hank Harris", "Street Art, Mural, Urban", 90),
        ("Ivy Irwin", "Wood, Sculpture", 80),
        ("Jack Jones", "Metal, Welding, Industrial", 87),
    ]
    
    artist_ids = []
    for name, tags, score in artists:
        email = f"{name.split()[0].lower()}@artist.com"
        c.execute('''INSERT INTO Users (Name, Role, Email, PasswordHash, AccountStatus) 
                     VALUES (%s, %s, %s, %s, %s) RETURNING UserID''',
                  (name, 'Artist', email, 'artist123', 'Active'))
        aid = c.fetchone()[0]
        artist_ids.append(aid)
        
        c.execute('INSERT INTO Performance (ArtistID, QualityScore, CapacityTag) VALUES (%s, %s, %s)', (aid, score, 'Available'))
        c.execute('INSERT INTO Portfolios (ArtistID, ImageURL, ArtStyleTags) VALUES (%s, %s, %s)', (aid, '/uploads/dummy.jpg', tags))

    past_deadline = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    
    c.execute('''INSERT INTO Tenders (Title, Description, TotalBudget, PlatformCommission, PayoutAmount, Deadline, AdminID)
                 VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING TenderID''',
              ("City Park Metallic Centerpiece", "Looking for a large scale modern metal sculpture for the new park.", 
               50000, 10, 45000, past_deadline, 1))
    tender_id = c.fetchone()[0]
    
    applicants = artist_ids[:8]
    
    for aid in applicants:
        c.execute("INSERT INTO Applications (TenderID, ArtistID) VALUES (%s, %s)", (tender_id, aid))
        
    conn.commit()
    conn.close()
    print("Database seeded with 10 artists, 1 past tender, and 8 applications.")

if __name__ == '__main__':
    seed()
