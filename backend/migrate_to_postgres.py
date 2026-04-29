import sqlite3
import psycopg2
import os

sqlite_db_path = os.path.join(os.path.dirname(__file__), 'arttender.db')
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/arttender')

def migrate_data():
    if not os.path.exists(sqlite_db_path):
        print("No SQLite database found. Nothing to migrate.")
        return

    print("Connecting to SQLite...")
    sqlite_conn = sqlite3.connect(sqlite_db_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_c = sqlite_conn.cursor()

    print("Connecting to PostgreSQL...")
    pg_conn = psycopg2.connect(DATABASE_URL)
    pg_c = pg_conn.cursor()

    tables = ['Users', 'Portfolios', 'Tenders', 'Applications', 'Milestones', 'Performance', 'AuditLogs']

    for table in tables:
        print(f"Migrating table {table}...")
        sqlite_c.execute(f"SELECT * FROM {table}")
        rows = sqlite_c.fetchall()

        if not rows:
            continue

        columns = rows[0].keys()
        col_names = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))

        # Insert rows
        insert_query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
        
        # Depending on triggers, we might need to temporarily disable them, but in our case, 
        # AuditLogs is append only, but we added a trigger to prevent UPDATE/DELETE, not INSERT.
        # So inserts should work.
        
        for row in rows:
            pg_c.execute(insert_query, tuple(row))
        
        # Reset the primary key sequence in PostgreSQL so new inserts don't fail
        pk_col = f"{table[:-1]}ID"
        if table == 'Users' or table == 'Tenders' or table == 'Applications' or table == 'Milestones' or table == 'Performance':
            pass
        
        if table == 'Users':
            pk_col = 'UserID'
        elif table == 'Portfolios':
            pk_col = 'PortfolioID'
        elif table == 'Tenders':
            pk_col = 'TenderID'
        elif table == 'Applications':
            pk_col = 'ApplicationID'
        elif table == 'Milestones':
            pk_col = 'MilestoneID'
        elif table == 'Performance':
            pk_col = 'RatingID'
        elif table == 'AuditLogs':
            pk_col = 'LogID'
            
        reset_query = f"SELECT setval(pg_get_serial_sequence('{table}', '{pk_col.lower()}'), coalesce(max({pk_col}), 1), max({pk_col}) IS NOT null) FROM {table};"
        try:
            pg_c.execute(reset_query)
        except Exception as e:
            print(f"Could not reset sequence for {table}: {e}")
            pg_conn.rollback()
            continue

    pg_conn.commit()
    sqlite_conn.close()
    pg_conn.close()
    print("Migration complete!")

if __name__ == '__main__':
    migrate_data()
