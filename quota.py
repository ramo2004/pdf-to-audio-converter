"""
Simple quota tracking to stay within Google Cloud TTS free tier.
Stores usage data in a JSON file in GCS.
"""
import json
import os
from datetime import datetime, timezone
from storage import download_blob, upload_blob

QUOTA_FILE_PATH = "quota/usage.json"


def get_quota_data():
    """Download and parse quota usage data from GCS."""
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
            tmp_path = tmp.name

        download_blob(QUOTA_FILE_PATH, tmp_path)

        with open(tmp_path, 'r') as f:
            data = json.load(f)

        import os
        os.remove(tmp_path)
        return data
    except Exception as e:
        # If file doesn't exist or error, return default structure
        # print(f"Could not load quota data, using defaults: {e}")
        if DEBUG:
            print(f"Could not load quota data, using defaults: {e}")
        return {
            "daily": {"date": None, "characters": 0},
            "monthly": {"month": None, "characters": 0}
        }


def save_quota_data(data):
    """Upload quota usage data to GCS."""
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
            json.dump(data, tmp, indent=2)
            tmp_path = tmp.name

        upload_blob(tmp_path, QUOTA_FILE_PATH)

        import os
        os.remove(tmp_path)
        # print(f"Quota data saved: {data}")
        if DEBUG:
            print(f"Quota data saved: {data}")
    except Exception as e:
        # print(f"Error saving quota data: {e}")
        if DEBUG:
            print(f"Error saving quota data: {e}")


def check_and_update_quota(characters_used):
    """
    Check if processing this many characters would exceed quotas.
    Returns (allowed: bool, message: str, remaining_daily: int, remaining_monthly: int)
    """
    DAILY_LIMIT = 50000
    MONTHLY_LIMIT = 1000000

    data = get_quota_data()
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    current_month = now.strftime("%Y-%m")

    # Check and reset daily quota if new day
    if data["daily"]["date"] != today:
        data["daily"] = {"date": today, "characters": 0}

    # Check and reset monthly quota if new month
    if data["monthly"]["month"] != current_month:
        data["monthly"] = {"month": current_month, "characters": 0}

    # Calculate remaining quotas
    daily_used = data["daily"]["characters"]
    monthly_used = data["monthly"]["characters"]

    remaining_daily = DAILY_LIMIT - daily_used
    remaining_monthly = MONTHLY_LIMIT - monthly_used

    # Check if this request would exceed limits
    if daily_used + characters_used > DAILY_LIMIT:
        return (
            False,
            f"Daily quota exceeded. Used {daily_used:,}/{DAILY_LIMIT:,} characters today. Resets at midnight UTC.",
            remaining_daily,
            remaining_monthly
        )

    if monthly_used + characters_used > MONTHLY_LIMIT:
        return (
            False,
            f"Monthly quota exceeded. Used {monthly_used:,}/{MONTHLY_LIMIT:,} characters this month. Resets on the 1st.",
            remaining_daily,
            remaining_monthly
        )

    # Update quotas
    data["daily"]["characters"] += characters_used
    data["monthly"]["characters"] += characters_used
    save_quota_data(data)

    return (
        True,
        f"Quota OK. Remaining today: {remaining_daily - characters_used:,} chars. This month: {remaining_monthly - characters_used:,} chars.",
        remaining_daily - characters_used,
        remaining_monthly - characters_used
    )


def get_quota_status():
    """Get current quota usage without updating."""
    DAILY_LIMIT = 50000
    MONTHLY_LIMIT = 1000000

    data = get_quota_data()
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    current_month = now.strftime("%Y-%m")

    # Reset if needed
    if data["daily"]["date"] != today:
        daily_used = 0
    else:
        daily_used = data["daily"]["characters"]

    if data["monthly"]["month"] != current_month:
        monthly_used = 0
    else:
        monthly_used = data["monthly"]["characters"]

    return {
        "daily": {"used": daily_used, "limit": DAILY_LIMIT, "remaining": DAILY_LIMIT - daily_used},
        "monthly": {"used": monthly_used, "limit": MONTHLY_LIMIT, "remaining": MONTHLY_LIMIT - monthly_used}
    }
DEBUG = os.getenv("DEBUG", "").lower() == "true"
