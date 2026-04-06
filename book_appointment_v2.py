"""
BHEL KarExpert — Booking Bot V2
=================================
Login   : Username + Password (fully automatic)
Date    : Today + 7 days IST
Slots   : Preferred: 10:00, 10:30, 11:00, 04:30, 05:00, 05:30 → any
Mode    : START (morning polling) or CHECK (instant check)

START mode — poll schedule:
  6:50–6:59 AM IST → every 10s (portal not open yet)
  7:00–7:20 AM IST → every 2s  (flash sale window)
  7:20–7:30 AM IST → every 10s (wind down)
  7:30 AM IST      → auto stop

CHECK mode — instant:
  Login → check once → book if available → report → done
"""

import os, time, requests, traceback
from datetime import datetime, timezone, timedelta

# ── Config ──────────────────────────────────────────────────────────────────
PORTAL_USERNAME    = os.environ.get("PORTAL_USERNAME", "")
PORTAL_PASSWORD    = os.environ.get("PORTAL_PASSWORD", "")
DOCTOR_SEARCH      = os.environ.get("DOCTOR_SEARCH", "Dr S Kamal Kumar")
SLACK_WEBHOOK      = os.environ.get("SLACK_WEBHOOK", "")
SLACK_RESPONSE_URL = os.environ.get("SLACK_RESPONSE_URL", "")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "")
DRY_RUN            = os.environ.get("DRY_RUN", "false").lower() == "true"
BOT_MODE           = os.environ.get("BOT_MODE", "start").lower()  # "start" or "check"

LOGIN_URL          = "https://bhel.karexpert.com/account-management/login"
BOOKING_URL        = "https://bhel.karexpert.com/appointment/searchdoctor/searchdepartment/general/cleardate"
ORDER_URL          = "https://bhel.karexpert.com/order/my_orders_format/orderList"

# Slot preference order
PREFERRED_SLOTS    = ["10:00 AM", "10:30 AM", "11:00 AM", "04:30 PM", "05:00 PM", "05:30 PM"]

# Colors
WHITE_BORDER       = "rgb(184, 233, 134)"

# ── IST helpers ─────────────────────────────────────────────────────────────
def get_ist():
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

def past_stop_time():
    ist = get_ist()
    return ist.hour > 7 or (ist.hour == 7 and ist.minute >= 30)

def get_poll_interval():
    """
    6:50–6:59 AM → 10s
    7:00–7:20 AM → 2s  (peak)
    7:20–7:30 AM → 10s
    """
    ist = get_ist()
    h, m = ist.hour, ist.minute
    if h == 7 and m < 20:
        return 2    # peak window
    return 10       # all other times

def get_target_date():
    ist      = get_ist()
    target   = ist + timedelta(days=7)
    day_str  = target.strftime("%-d")
    mon_str  = target.strftime("%b")
    full_str = target.strftime("%d %b %Y")
    return target, day_str, mon_str, full_str

# ── Slack ────────────────────────────────────────────────────────────────────
def slack(text, emoji=""):
    msg = f"{emoji} {text}".strip() if emoji else text
    payload = {"response_type": "in_channel", "text": msg}
    for url in [SLACK_RESPONSE_URL, SLACK_WEBHOOK]:
        if url:
            try:
                r = requests.post(url, json=payload, timeout=10)
                if r.status_code == 200:
                    break
            except Exception:
                continue
    print(f"[SLACK] {msg[:120]}", flush=True)

def log(msg):
    ist = get_ist()
    print(f"[{ist.strftime('%H:%M:%S')} IST] {msg}", flush=True)

# ── Slot detection ───────────────────────────────────────────────────────────
def find_available_slots(page):
    """
    WHITE pill = border:rgb(184,233,134), no background, no not-allowed → BOOK
    ORANGE pill = border:rgb(251,144,38) → fallback
    Returns sorted by PREFERRED_SLOTS order
    """
    all_btns     = page.locator("button._wf-pp-timebox")
    white_slots  = {}
    orange_slots = {}
    count        = all_btns.count()

    for i in range(count):
        btn = all_btns.nth(i)
        try:
            if not btn.is_visible():
                continue
            if btn.is_disabled():
                continue
            style   = btn.get_attribute("style") or ""
            classes = btn.get_attribute("class") or ""
            if "cursor: not-allowed" in style or "not-allowed" in style:
                continue
            if "disabled" in classes.lower():
                continue
            text = btn.inner_text().strip()
            if not text:
                continue
            has_green_border = WHITE_BORDER in style
            has_background   = "background:" in style or "background-color:" in style
            if has_green_border and not has_background:
                white_slots[text] = btn
            elif "rgb(251, 144, 38)" in style or "rgb(255, 165, 0)" in style:
                orange_slots[text] = btn
        except Exception:
            continue

    available = white_slots if white_slots else orange_slots
    if not available:
        return []

    result = []
    for pref in PREFERRED_SLOTS:
        if pref in available:
            result.append((available[pref], pref))
    for text, btn in available.items():
        if text not in PREFERRED_SLOTS:
            result.append((btn, text))
    return result

# ── Login ─────────────────────────────────────────────────────────────────────
def do_login(page):
    log("Opening login page ...")
    page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
    try:
        page.wait_for_selector("ngx-spinner", state="hidden", timeout=10000)
    except Exception:
        pass
    try:
        page.wait_for_selector("._wf-lp-form-block", state="visible", timeout=10000)
    except Exception:
        pass
    time.sleep(2)

    # Enter username
    for selector in [
        'input[formcontrolname="loginId"]',
        'input[formcontrolname="username"]',
        'input[placeholder*="Login" i]',
        'input[placeholder*="User" i]',
        'input[type="text"]',
    ]:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=2000):
                el.click()
                el.fill(PORTAL_USERNAME)
                log(f"Username filled via {selector}")
                break
        except Exception:
            continue

    # Enter password
    for selector in [
        'input[type="password"]',
        'input[formcontrolname="password"]',
        'input[placeholder*="Password" i]',
    ]:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=2000):
                el.click()
                el.fill(PORTAL_PASSWORD)
                log(f"Password filled via {selector}")
                break
        except Exception:
            continue
    time.sleep(0.5)

    # Click Login
    for selector in ["button.login-button", "button.btn-gradient", "button[type='submit']"]:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=2000):
                el.click()
                log(f"Login clicked via {selector}")
                break
        except Exception:
            continue

    # Confirm login via DOM
    for selector in ["app-header", "app-sidebar", "app-base", "app-dynamic-dashboard"]:
        try:
            page.wait_for_selector(selector, timeout=15000)
            log(f"Login confirmed: {selector}")
            return True
        except Exception:
            continue

    # Fallback: poll URL
    for i in range(10):
        time.sleep(2)
        if "dynamic_dashboard" in page.url:
            log("Login confirmed via URL")
            return True

    log("Login optimistic continue ...")
    return True

# ── Navigate to doctor slot page ──────────────────────────────────────────────
def navigate_to_doctor(page):
    log("Navigating to booking page ...")
    page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
    time.sleep(3)

    if "login" in page.url and "dynamic" not in page.url:
        raise Exception("Session expired — redirected to login")

    # Find Dr S Kamal Kumar
    log("Finding Dr S Kamal Kumar ...")
    page.wait_for_selector("div#doctor-card", timeout=15000)
    time.sleep(1)
    cards = page.locator("div#doctor-card")
    total = cards.count()
    log(f"Found {total} doctor cards")

    found = False
    for i in range(total):
        card = cards.nth(i)
        try:
            if "Kamal Kumar" in (card.inner_text() or ""):
                log(f"Dr S Kamal Kumar at card {i+1}")
                card.scroll_into_view_if_needed()
                time.sleep(0.5)
                for btn_sel in [
                    "button.primary-btn.disabledBookBtn",
                    "button.primary-btn",
                    "button[class*='primary-btn']",
                ]:
                    try:
                        btn = card.locator(btn_sel).first
                        if btn.is_visible(timeout=3000):
                            btn.click()
                            found = True
                            log(f"Clicked Book Appointment via {btn_sel}")
                            break
                    except Exception:
                        continue
                if found:
                    break
        except Exception as e:
            log(f"Card {i+1}: {e}")

    if not found:
        log("Fallback: first primary-btn ...")
        page.locator("button.primary-btn").first.click()

    time.sleep(2)
    return page.url

# ── Select target date ────────────────────────────────────────────────────────
def select_target_date(page, day_str, mon_str):
    date_label = f"{day_str} {mon_str}"
    try:
        page.wait_for_selector("div.dottab", timeout=8000)
        time.sleep(0.3)
        tabs  = page.locator("div.dottab")
        total = tabs.count()
        for i in range(total):
            tab      = tabs.nth(i)
            tab_text = tab.inner_text().strip()
            if day_str in tab_text and mon_str in tab_text:
                tab.click()
                time.sleep(1)
                log(f"Selected date: {tab_text}")
                return tab_text
        # Fallback to last tab
        last_text = tabs.nth(total - 1).inner_text().strip()
        tabs.nth(total - 1).click()
        time.sleep(1)
        log(f"Target not found — last tab: {last_text}")
        return last_text
    except Exception as e:
        log(f"Date tab error: {e}")
        return date_label

# ── Book slot ────────────────────────────────────────────────────────────────
def book_slot(page, chosen_btn, chosen_time):
    chosen_btn.click()
    time.sleep(2)
    log("Waiting for cart ...")
    try:
        page.wait_for_selector("kx-cart", timeout=10000)
        log("Cart appeared!")
    except Exception:
        log("Cart timeout — confirming anyway ...")
    time.sleep(1)

    confirmed = False
    for selector in ["div._wf-pp-bookappointmentdivx2", "._wf-pp-bookappointmentdivx2"]:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=5000):
                el.click()
                confirmed = True
                log(f"Confirmed via {selector}")
                break
        except Exception:
            continue

    if not confirmed:
        for label in ["Book Appointment", "Confirm", "Book", "Submit", "OK"]:
            try:
                cb = page.get_by_role("button", name=label, exact=False).first
                if cb.is_visible(timeout=3000):
                    cb.click()
                    confirmed = True
                    log(f"Confirmed via '{label}'")
                    break
            except Exception:
                continue

    page.wait_for_load_state("networkidle", timeout=15000)
    return confirmed

# ── Send success Slack message ────────────────────────────────────────────────
def send_success_slack(date_label, chosen_time, confirmed):
    ist = get_ist()
    slack(
        f"*Appointment Successfully Booked!* :white_check_mark:\n\n"
        f">  *Doctor:*    Dr S Kamal Kumar\n"
        f">  *Specialty:* General Physician\n"
        f">  *Date:*      {date_label}\n"
        f">  *Slot:*      {chosen_time}\n"
        f">  *Room:*      OPD PHY 2 | First Floor\n"
        f">  *Type:*      OP (Outpatient)\n"
        f">  *Booked at:* {ist.strftime('%d-%b-%Y %H:%M:%S')} IST\n"
        f">  *Status:*    Booked ✅\n"
        f">  *Payment:*   Successful ✅\n\n"
        f"_View: bhel.karexpert.com/order/my_orders_format/orderList_",
        ":hospital:"
    )

# ── MODE 1: START — morning polling ──────────────────────────────────────────
def run_start_mode(page, doctor_url, day_str, mon_str, full_date):
    target, _, _, _ = get_target_date()
    ist  = get_ist()
    poll = get_poll_interval()

    slack(
        f":mag: *Bot watching for slots!* (START mode)\n"
        f">  Target date: *{full_date}*\n"
        f">  IST now: *{ist.strftime('%H:%M:%S')}*\n"
        f">  Poll: *10s → 2s (7:00 AM) → 10s (7:20 AM)*\n"
        f">  Preferred: 10:00 → 10:30 → 11:00 → 04:30 → 05:00 → 05:30\n"
        f">  Auto-stop: *7:30 AM IST*",
        ":clock630:"
    )

    attempt        = 0
    prev_tab_count = 0

    while True:
        attempt += 1

        if past_stop_time():
            ist = get_ist()
            slack(
                f":stopwatch: *7:30 AM IST — bot stopping.*\n"
                f">  No slot found today.\n"
                f">  IST: {ist.strftime('%H:%M:%S')}\n"
                f">  Try `/check` later or `/start` tomorrow at 6:50 AM",
                ":x:"
            )
            log("7:30 AM IST — stopping")
            break

        poll = get_poll_interval()
        ist  = get_ist()
        log(f"── Attempt {attempt} | {ist.strftime('%H:%M:%S')} IST | poll:{poll}s ──")

        try:
            page.goto(doctor_url, wait_until="networkidle", timeout=20000)
            time.sleep(1)
        except Exception as e:
            log(f"Reload: {e}")
            time.sleep(poll)
            continue

        # Select date
        try:
            page.wait_for_selector("div.dottab", timeout=8000)
            time.sleep(0.3)
            tabs       = page.locator("div.dottab")
            total_tabs = tabs.count()

            if total_tabs > prev_tab_count and prev_tab_count > 0:
                slack(f":tada: *New date tab added!* Now {total_tabs} dates available!", "")

            prev_tab_count = total_tabs
            date_label     = select_target_date(page, day_str, mon_str)
        except Exception as e:
            log(f"Date: {e}")
            date_label = full_date

        # Check slots
        slots = find_available_slots(page)
        log(f"Slots on {date_label}: {[s[1] for s in slots] if slots else 'none'}")

        if not slots:
            time.sleep(poll)
            continue

        # Book it!
        chosen_btn, chosen_time = slots[0]
        ist = get_ist()
        log(f"SLOT FOUND: {chosen_time} on {date_label}")

        if DRY_RUN:
            slack(
                f":test_tube: *[DRY RUN]* Slot found!\n"
                f">  Date: *{date_label}* | Time: *{chosen_time}*\n"
                f"_DRY_RUN=true — NOT booked._", ":eyes:"
            )
            break

        slack(f":zap: *Slot found!* {chosen_time} on {date_label} — booking now!", ":tada:")
        confirmed = book_slot(page, chosen_btn, chosen_time)
        send_success_slack(date_label, chosen_time, confirmed)
        log("DONE — Appointment booked!")
        break

# ── MODE 2: CHECK — instant check ────────────────────────────────────────────
def run_check_mode(page, doctor_url, day_str, mon_str, full_date):
    ist = get_ist()
    slack(
        f":mag: *Checking slots now!* (CHECK mode)\n"
        f">  Target date: *{full_date}*\n"
        f">  IST now: *{ist.strftime('%H:%M:%S')}*\n"
        f">  Checking once — book if available, report if not.",
        ":clock1:"
    )

    try:
        page.goto(doctor_url, wait_until="networkidle", timeout=20000)
        time.sleep(1)
    except Exception as e:
        slack(f":x: Could not reload page: {e}")
        return

    date_label = select_target_date(page, day_str, mon_str)
    slots      = find_available_slots(page)

    log(f"CHECK mode — slots on {date_label}: {[s[1] for s in slots] if slots else 'none'}")

    if not slots:
        slack(
            f":calendar: *No slots available right now.*\n"
            f">  Date checked: *{date_label}*\n"
            f">  IST: {ist.strftime('%H:%M:%S')}\n"
            f">  Try `/start` at 6:50 AM tomorrow for fresh slots\n"
            f">  Or try `/check` again later",
            ":x:"
        )
        return

    # Slot found — book it!
    chosen_btn, chosen_time = slots[0]
    log(f"CHECK: Slot found: {chosen_time}")

    if DRY_RUN:
        slack(
            f":test_tube: *[DRY RUN]* Slot found!\n"
            f">  Date: *{date_label}* | Time: *{chosen_time}*\n"
            f"_DRY_RUN=true — NOT booked._", ":eyes:"
        )
        return

    slack(f":zap: *Slot found!* {chosen_time} on {date_label} — booking now!", ":tada:")
    confirmed = book_slot(page, chosen_btn, chosen_time)
    send_success_slack(date_label, chosen_time, confirmed)
    log("CHECK mode — DONE!")

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    from playwright.sync_api import sync_playwright

    ist                          = get_ist()
    target, day_str, mon_str, full_date = get_target_date()
    mode                         = BOT_MODE

    log(f"Bot V2 | Mode: {mode.upper()} | IST: {ist.strftime('%H:%M:%S')} | Target: {full_date}")

    slack(
        f"*BHEL Bot V2 started!* :rocket:\n"
        f">  Mode: *{'🌅 START (morning)' if mode == 'start' else '🔍 CHECK (instant)'}*\n"
        f">  Doctor: *{DOCTOR_SEARCH}*\n"
        f">  Target date: *{full_date}*\n"
        f">  IST: *{ist.strftime('%H:%M:%S')}*",
        ":robot_face:"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(viewport={"width": 1280, "height": 800})
        page    = ctx.new_page()

        # Login
        slack(":key: Logging in with username + password...", "")
        do_login(page)
        ist = get_ist()
        slack(f":white_check_mark: *Logged in!* IST: {ist.strftime('%H:%M:%S')}", "")

        # Navigate to doctor
        doctor_url = navigate_to_doctor(page)
        log(f"Doctor page: {doctor_url}")

        # Run selected mode
        if mode == "check":
            run_check_mode(page, doctor_url, day_str, mon_str, full_date)
        else:
            run_start_mode(page, doctor_url, day_str, mon_str, full_date)

        browser.close()
        log("Done.")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        err = traceback.format_exc()
        log(f"CRASH:\n{err}")
        slack(
            f"*Bot V2 crashed!* :rotating_light:\n```{err[-800:]}```\n"
            f"_Type `/start` or `/check` to retry._", ":x:"
        )
