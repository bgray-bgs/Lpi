import datetime
import pytz
from astral.sun import sun
from astral import LocationInfo
from gpiozero import LED

# -------- Configuration --------
GPIO_PIN = 18          # BCM pin
LIGHT_OFF_HOUR = 1     # Light OFF time (1:00 AM)
USE_TEST_TIME = False  # Set True to simulate time

# Location (Rochester, NY)
city = LocationInfo(
    "Rochester",
    "USA",
    "America/New_York",
    43.2086,
    -77.4623
)

# -------- GPIO Setup --------
light = LED(GPIO_PIN, active_high=True)

def LightOn():
    light.on()
    print("Light ON (GPIO HIGH)")

def LightOff():
    light.off()
    print("Light OFF (GPIO LOW)")

def safe_localize(tz, naive_dt):
    """
    Make a timezone-aware datetime safely across DST transitions.

    - If time is ambiguous (fall back): choose the later occurrence (standard time) via is_dst=False.
    - If time is nonexistent (spring forward): shift forward 1 hour and localize.
    """
    try:
        return tz.localize(naive_dt, is_dst=None)
    except pytz.AmbiguousTimeError:
        # Fall back: time happens twice; pick the later occurrence (standard time)
        return tz.localize(naive_dt, is_dst=False)
    except pytz.NonExistentTimeError:
        # Spring forward: time doesn't exist; bump forward by 1 hour
        bumped = naive_dt + datetime.timedelta(hours=1)
        return tz.localize(bumped, is_dst=None)

# -------- Main Logic --------
def main():
    local_tz = pytz.timezone(city.timezone)

    # ---- Time Setup ----
    if USE_TEST_TIME:
        test_time_naive = datetime.datetime(2025, 7, 24, 2, 45)
        now_local = local_tz.localize(test_time_naive)
        print("!!! TEST MODE ENABLED !!!")
    else:
        now_local = datetime.datetime.now(local_tz)

    # ---- Sunset Reference Date ----
    if now_local.time() < datetime.time(LIGHT_OFF_HOUR, 0):
        sunset_reference_date = now_local.date() - datetime.timedelta(days=1)
    else:
        sunset_reference_date = now_local.date()

    # ---- Sunset + ON/OFF Times ----
    s = sun(city.observer, date=sunset_reference_date, tzinfo=local_tz)

    sunset_local = s["sunset"]
    lighton_local = sunset_local - datetime.timedelta(hours=1)

    # OFF time is "tomorrow at LIGHT_OFF_HOUR:00" relative to sunset_reference_date
    off_date = sunset_reference_date + datetime.timedelta(days=1)
    lightoff_naive = datetime.datetime.combine(off_date, datetime.time(LIGHT_OFF_HOUR, 0))
    lightoff_local = safe_localize(local_tz, lightoff_naive)

    # ---- Debug Output ----
    def clean(dt):
        return dt.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

    print("===== DEBUG TIMING =====")
    print("Current local time:     ", clean(now_local))
    print("Sunset date used:       ", sunset_reference_date)
    print("Sunset time (local):    ", clean(sunset_local))
    print("Light ON time:          ", clean(lighton_local))
    print("Light OFF time:         ", clean(lightoff_local))
    print("========================")

    # ---- ON / OFF Decision ----
    if lighton_local <= now_local < lightoff_local:
        LightOn()
    else:
        LightOff()

# -------- Entry Point --------
if __name__ == "__main__":
    main()
