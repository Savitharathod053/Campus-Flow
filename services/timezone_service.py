"""
Campus Flow - Timezone Utility Service
Centralized timezone management strictly enforcing Indian Standard Time (IST, Asia/Kolkata, UTC+05:30)
for attendance timestamps across the backend, APIs, and database interactions.
"""
from datetime import datetime, timezone, date, time
from zoneinfo import ZoneInfo
from typing import Optional, Union
import logging

logger = logging.getLogger(__name__)

# Canonical Timezones
IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc

def get_current_attendance_time() -> datetime:
    """
    Returns the current timestamp to be stored for attendance records.
    Always returns a timezone-aware UTC datetime.
    """
    return datetime.now(UTC)

def get_current_ist_time() -> datetime:
    """
    Returns the current datetime in Indian Standard Time (Asia/Kolkata).
    """
    return datetime.now(IST)

def get_current_utc_time() -> datetime:
    """
    Returns the current datetime in UTC.
    """
    return datetime.now(UTC)

def to_ist(dt: Union[datetime, str, None]) -> Optional[datetime]:
    """
    Converts a datetime or ISO timestamp string into a timezone-aware IST (Asia/Kolkata) datetime.
    
    Safe from double-conversion:
    - If dt is already in Asia/Kolkata (or +05:30 offset), astimezone(IST) leaves the wall clock unchanged.
    - If dt is timezone-naive, it assumes UTC (how timestamps are persisted in the database)
      and safely attaches UTC before converting to IST.
    - If dt is already in UTC, it converts properly to IST.
    """
    if dt is None:
        return None

    if isinstance(dt, str):
        cleaned = dt.strip()
        if not cleaned:
            return None
        # Handle ISO format
        try:
            # Replace trailing Z with +00:00 for fromisoformat compatibility
            if cleaned.endswith('Z'):
                cleaned = cleaned[:-1] + '+00:00'
            dt = datetime.fromisoformat(cleaned)
        except Exception:
            for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
                try:
                    dt = datetime.strptime(cleaned, fmt)
                    break
                except ValueError:
                    continue

    if not isinstance(dt, datetime):
        return None

    if dt.tzinfo is None:
        # Naive datetime from database, which was saved as UTC
        dt = dt.replace(tzinfo=UTC)

    return dt.astimezone(IST)

def to_utc(dt: Union[datetime, str, None]) -> Optional[datetime]:
    """
    Converts a datetime into timezone-aware UTC datetime.
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        return to_ist(dt).astimezone(UTC)
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)

def format_ist_datetime(dt: Union[datetime, str, None], fmt: str = '%d %B %Y, %I:%M %p IST') -> str:
    """
    Converts dt to IST and formats it as e.g. '22 September 2026, 01:05 PM IST'.
    """
    ist_dt = to_ist(dt)
    if not ist_dt:
        return ''
    return ist_dt.strftime(fmt)

def format_ist_time(dt: Union[datetime, time, str, None], fmt: str = '%I:%M %p IST') -> str:
    """
    Converts dt to IST and formats time as e.g. '01:05 PM IST'.
    If dt is a time object, formats it directly with 'IST' suffix.
    """
    if dt is None:
        return ''
    if isinstance(dt, time):
        return f"{dt.strftime('%I:%M %p')} IST"
    ist_dt = to_ist(dt)
    if not ist_dt:
        return ''
    return ist_dt.strftime(fmt)

def format_ist_date(dt: Union[datetime, date, str, None], fmt: str = '%d %B %Y') -> str:
    """
    Converts dt to IST and formats date as e.g. '22 September 2026'.
    """
    if dt is None:
        return ''
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.strftime(fmt)
    ist_dt = to_ist(dt)
    if not ist_dt:
        return ''
    return ist_dt.strftime(fmt)
