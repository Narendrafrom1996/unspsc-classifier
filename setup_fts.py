import sqlite3
import time
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'unspsc_data.sqlite')

def setup_fts():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='unspsc_fts'")
    table_exists = cursor.fetchone() is not None

    needs_populate = False
    if not table_exists:
        print("Creating unspsc_fts table...")
        cursor.execute("""
            CREATE VIRTUAL TABLE unspsc_fts USING fts5(
                commodity_code UNINDEXED,
                commodity_name,
                class_code UNINDEXED,
                class_name,
                family_code UNINDEXED,
                family_name,
                segment_code UNINDEXED,
                segment_name,
                tokenize='porter unicode61'
            )
        """)
        needs_populate = True
    else:
        cursor.execute("SELECT COUNT(*) FROM unspsc_fts")
        count = cursor.fetchone()[0]
        if count == 0:
            needs_populate = True
        else:
            print(f"unspsc_fts already exists with {count} rows.")

    if needs_populate:
        t0 = time.time()
        print("Populating unspsc_fts from unspsc_items...")
        cursor.execute("""
            INSERT INTO unspsc_fts (
                commodity_code, commodity_name,
                class_code, class_name,
                family_code, family_name,
                segment_code, segment_name
            )
            SELECT
                commodity_code, commodity_name,
                class_code, class_name,
                family_code, family_name,
                segment_code, segment_name
            FROM unspsc_items
        """)
        conn.commit()
        print(f"Populated unspsc_fts in {time.time() - t0:.2f} seconds.")
    
    conn.close()

if __name__ == '__main__':
    setup_fts()
