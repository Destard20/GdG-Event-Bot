import os
import re
import sys
import zipfile
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import List, Optional


def zip_completed_months(logs_dir: str, current_date: Optional[datetime] = None) -> List[str]:
    """
    Checks the logs directory for daily log files belonging to ended months.
    Zips all daily log files from ended months into bot_logs_YYYY-MM.zip and
    deletes the uncompressed daily files.

    Returns a list of zip file paths created or updated.
    """
    if not os.path.exists(logs_dir):
        return []

    now = current_date or datetime.now()
    current_year = now.year
    current_month = now.month

    # Group files by (year, month)
    monthly_files = {}

    for fname in os.listdir(logs_dir):
        fpath = os.path.join(logs_dir, fname)
        if not os.path.isfile(fpath) or fname.endswith(".zip"):
            continue

        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", fname)
        if not m:
            continue

        f_year = int(m.group(1))
        f_month = int(m.group(2))

        # Check if the file belongs to an already ended month
        if (f_year, f_month) < (current_year, current_month):
            key = (f_year, f_month)
            if key not in monthly_files:
                monthly_files[key] = []
            monthly_files[key].append(fpath)

    archived_zips = []

    for (year, month), files in sorted(monthly_files.items()):
        zip_name = f"bot_logs_{year:04d}-{month:02d}.zip"
        zip_path = os.path.join(logs_dir, zip_name)

        try:
            with zipfile.ZipFile(zip_path, 'a', zipfile.ZIP_DEFLATED) as zipf:
                existing = set(zipf.namelist())
                for file_path in files:
                    arcname = os.path.basename(file_path)
                    if arcname not in existing:
                        zipf.write(file_path, arcname)

            for file_path in files:
                try:
                    os.remove(file_path)
                except OSError as e:
                    sys.stderr.write(f"Warning: Could not remove log file {file_path}: {e}\n")

            archived_zips.append(zip_path)
        except Exception as e:
            sys.stderr.write(f"Error creating zip archive {zip_path}: {e}\n")

    return archived_zips


class DailyMonthlyLogHandler(TimedRotatingFileHandler):
    """
    TimedRotatingFileHandler that rotates daily at midnight.
    Upon rollover (and on initial setup), checks if the previous month has ended
    and compresses all daily log files from ended months into a monthly zip archive.
    """
    def __init__(self, filename, when="midnight", interval=1, backupCount=0, encoding="utf-8", **kwargs):
        super().__init__(filename, when=when, interval=interval, backupCount=backupCount, encoding=encoding, **kwargs)
        self.check_and_zip()

    def check_and_zip(self):
        try:
            logs_dir = os.path.dirname(self.baseFilename)
            zip_completed_months(logs_dir)
        except Exception as e:
            sys.stderr.write(f"Error checking and zipping monthly logs: {e}\n")

    def doRollover(self):
        super().doRollover()
        self.check_and_zip()
