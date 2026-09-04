import sqlite3
import os
import glob
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import DB_PATH, DATA_DIR

def clean():
    # 1. Clean the Database
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM events")
        cursor.execute("DELETE FROM reservations")
        # Reset the autoincrement ID back to 1
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='events'")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='reservations'")
        conn.commit()
        conn.close()
        print("✅ Database tables 'events' and 'reservations' have been cleared.")
    except Exception as e:
        print(f"❌ Error cleaning database: {e}")

    # 2. Clean the Data Folder (delete all .jpg images recursively)
    try:
        image_files = glob.glob(os.path.join(DATA_DIR, "**", "*.jpg"), recursive=True)
        for file in image_files:
            os.remove(file)
        print(f"✅ Deleted {len(image_files)} image files from {DATA_DIR} and its subdirectories.")
    except Exception as e:
        print(f"❌ Error deleting images: {e}")

    # 3. Clean empty folders inside DATA_DIR
    try:
        deleted_folders = 0
        # Walk bottom-up so child folders are removed before parent folders
        for root, dirs, files in os.walk(DATA_DIR, topdown=False):
            # Never delete DATA_DIR itself
            if os.path.abspath(root) == os.path.abspath(DATA_DIR):
                continue
            if not os.listdir(root):
                try:
                    os.rmdir(root)
                    deleted_folders += 1
                except OSError as err:
                    print(f"⚠️ Could not delete folder {root}: {err}")
        print(f"✅ Deleted {deleted_folders} empty folders from {DATA_DIR}.")
    except Exception as e:
        print(f"❌ Error deleting empty folders: {e}")

if __name__ == '__main__':
    clean()
