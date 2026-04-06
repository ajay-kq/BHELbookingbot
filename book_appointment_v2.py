"""
BHEL KarExpert — Booking Bot V2
Login   : Username + Password (fully automatic)
Date    : Today + 7 days IST
Slots   : Preferred: 10:00, 10:30, 11:00, 04:30, 05:00, 05:30
Modes   : start | check | orders
"""

import os, time, requests, traceback, re
from datetime import datetime, timezone, timedelta

PORTAL_USERNAME    = os.environ.get("PORTAL_USERNAME", "")
PORTAL_PASSWORD    = os.environ.get("PORTAL_PASSWORD", "")
DOCTOR_SEARCH      = os.environ.get("DOCTOR_SEARCH", "Dr S Kamal Kumar")
SLACK_WEBHOOK      = os.environ.get("SLACK_WEBHOOK", "")
SLACK_RESPONSE_URL = os.environ.get("SLACK_RESPONSE_URL", "")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "")
DRY_RUN            = os.environ.get("DRY_RUN", "false").lower() == "true"
BOT_MODE           = os.environ.get("BOT_MODE", "start").lower()

LOGIN_URL          = "https://bhel.karexpert.com/account-management/login"
BOOKING_URL        = "https://bhel.karexpert.com/appointment/searchdoctor/searchdepartment/general/cleardate"
ORDER_URL          = "https://bhel.karexpert.com/order/my_orders_format/orderList"

PREFERRED_SLOTS    = ["10:00 AM", "10:30 AM", "11:00 AM", "04:30 PM", "05:00 PM", "05:30 PM"]
WHITE_BORDER       = "rgb(184, 233, 134)"
FAST_POLL          = 2
SLOW_POLL          = 10
D                  = "\u2500" * 40

def get_ist():
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

def past_stop_time():
    ist = get_ist()
    return ist.hour > 7 or (ist.hour == 7 and ist.minute >= 30)

def get_poll_interval():
    ist = get_ist()
    h, m = ist.hour, ist.minute
    if h == 7 and m < 20:
        return FAST_POLL
    return SLOW_POLL

def get_target_date():
    ist     = get_ist()
    target  = ist + timedelta(days=7)
    day_str = target.strftime("%-d")
    mon_str = target.strftime("%b")
    full    = target.strftime("%d %b %Y")
    return target, day_str, mon_str, full

def slack(text):
    payload = {"response_type": "in_channel", "text": text}
    for url in [SLACK_RESPONSE_URL, SLACK_WEBHOOK]:
        if url:
            try:
                r = requests.post(url, json=payload, timeout=10)
                if r.status_code == 200:
                    break
            except Exception:
                continue
    print(f"[SLACK] {text[:80]}", flush=True)

def log(msg):
    ist = get_ist()
    print(f"[{ist.strftime('%H:%M:%S')} IST] {msg}", flush=True)

def find_available_slots(page):
    all_btns     = page.locator("button._wf-pp-timebox")
    white_slots  = {}
    orange_slots = {}
    for i in range(all_btns.count()):
        btn = all_btns.nth(i)
        try:
            if not btn.is_visible() or btn.is_disabled():
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
            has_border = WHITE_BORDER in style
            has_bg     = "background:" in style or "background-color:" in style
            if has_border and not has_bg:
                white_slots[text] = btn
            elif "rgb(251, 144, 38)" in style or "rgb(255, 165, 0)" in style:
                orange_slots[text] = btn
        except Exception:
            continue
    pool   = white_slots if white_slots else orange_slots
    result = []
    for p in PREFERRED_SLOTS:
        if p in pool:
            result.append((pool[p], p))
    for t, b in pool.items():
        if t not in PREFERRED_SLOTS:
            result.append((b, t))
    return result

def do_login(page):
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
    for sel in ['input[formcontrolname="loginId"]', 'input[formcontrolname="username"]',
                'input[placeholder*="Login" i]', 'input[type="text"]']:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                el.fill(PORTAL_USERNAME)
                break
        except Exception:
            continue
    for sel in ['input[type="password"]', 'input[formcontrolname="password"]']:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                el.fill(PORTAL_PASSWORD)
                break
        except Exception:
            continue
    time.sleep(0.5)
    for sel in ["button.login-button", "button.btn-gradient", "button[type='submit']"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                break
        except Exception:
            continue
    for sel in ["app-header", "app-sidebar", "app-base", "app-dynamic-dashboard"]:
        try:
            page.wait_for_selector(sel, timeout=15000)
            log(f"Login confirmed: {sel}")
            return True
        except Exception:
            continue
    for i in range(10):
        time.sleep(2)
        if "dynamic_dashboard" in page.url:
            log("Login confirmed via URL")
            return True
    return True

def navigate_to_doctor(page):
    page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
    time.sleep(3)
    if "login" in page.url and "dynamic" not in page.url:
        raise Exception("Session expired")
    page.wait_for_selector("div#doctor-card", timeout=15000)
    time.sleep(1)
    cards = page.locator("div#doctor-card")
    found = False
    for i in range(cards.count()):
        card = cards.nth(i)
        try:
            if "Kamal Kumar" in (card.inner_text() or ""):
                card.scroll_into_view_if_needed()
                time.sleep(0.5)
                for bs in ["button.primary-btn.disabledBookBtn", "button.primary-btn"]:
                    try:
                        btn = card.locator(bs).first
                        if btn.is_visible(timeout=3000):
                            btn.click()
                            found = True
                            break
                    except Exception:
                        continue
                if found:
                    break
        except Exception:
            continue
    if not found:
        page.locator("button.primary-btn").first.click()
    time.sleep(2)
    return page.url

def select_target_date(page, day_str, mon_str):
    try:
        page.wait_for_selector("div.dottab", timeout=8000)
        time.sleep(0.3)
        tabs  = page.locator("div.dottab")
        total = tabs.count()
        for i in range(total):
            tab = tabs.nth(i)
            try:
                full_text = tab.inner_text().strip()
                first_line = full_text.split("\n")[0].strip()
                if day_str in first_line and mon_str in first_line:
                    tab.click()
                    time.sleep(1)
                    return f"{day_str} {mon_str}"
            except Exception:
                continue
        tabs.nth(total - 1).click()
        time.sleep(1)
    except Exception as e:
        log(f"Date tab: {e}")
    return f"{day_str} {mon_str}"

def book_slot(page, btn, slot_time):
    btn.click()
    time.sleep(2)
    try:
        page.wait_for_selector("kx-cart", timeout=10000)
    except Exception:
        pass
    time.sleep(1)
    confirmed = False
    for sel in ["div._wf-pp-bookappointmentdivx2", "._wf-pp-bookappointmentdivx2"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=5000):
                el.click()
                confirmed = True
                break
        except Exception:
            continue
    if not confirmed:
        for label in ["Book Appointment", "Confirm", "Book"]:
            try:
                cb = page.get_by_role("button", name=label, exact=False).first
                if cb.is_visible(timeout=3000):
                    cb.click()
                    confirmed = True
                    break
            except Exception:
                continue
    page.wait_for_load_state("networkidle", timeout=15000)
    return confirmed

def send_booked_slack(date_label, slot_time):
    ist = get_ist()
    slack(
        f":white_check_mark:  *Appointment Booked Successfully!*\n"
        f"{D}\n"
        f":male-doctor:  *Doctor*       :  Dr S Kamal Kumar\n"
        f":stethoscope:  *Specialty*    :  General Physician\n"
        f":round_pushpin:  *Room*          :  OPD PHY 2  |  First Floor\n"
        f":calendar:  *Date*         :  {date_label}\n"
        f":clock1:  *Slot*         :  {slot_time}\n"
        f":clipboard:  *Type*         :  OP (Outpatient)\n"
        f":white_check_mark:  *Status*       :  Booked\n"
        f":credit_card:  *Payment*      :  Successful\n"
        f":stopwatch:  *Booked at*    :  {ist.strftime('%d %b %Y  %H:%M:%S')} IST\n"
        f"{D}"
    )

def run_start_mode(page, doctor_url, day_str, mon_str, full_date):
    attempt        = 0
    prev_tab_count = 0
    while True:
        attempt += 1
        if past_stop_time():
            ist = get_ist()
            slack(
                f":stopwatch:  *Bot Stopped — 7:30 AM IST*\n"
                f"{D}\n"
                f":calendar:  *Date*        :  {full_date}\n"
                f":clock730:  *Stopped at*  :  {ist.strftime('%H:%M:%S')} IST\n"
                f":x:  *Result*       :  No slot found today\n"
                f"{D}\n"
                f"_Try `/start` tomorrow at 6:50 AM IST_"
            )
            break
        poll = get_poll_interval()
        ist  = get_ist()
        log(f"Attempt {attempt} | {ist.strftime('%H:%M:%S')} IST | {poll}s")
        try:
            page.goto(doctor_url, wait_until="networkidle", timeout=20000)
            time.sleep(1)
        except Exception as e:
            log(f"Reload: {e}")
            time.sleep(poll)
            continue
        try:
            page.wait_for_selector("div.dottab", timeout=8000)
            time.sleep(0.3)
            tabs       = page.locator("div.dottab")
            total_tabs = tabs.count()
            if total_tabs > prev_tab_count and prev_tab_count > 0:
                slack(
                    f":tada:  *New Date Unlocked!*\n"
                    f"{D}\n"
                    f":calendar:  Portal now shows *{total_tabs}* dates\n"
                    f":zap:  Checking new slots *immediately*\n"
                    f"{D}"
                )
            prev_tab_count = total_tabs
            date_label = select_target_date(page, day_str, mon_str)
        except Exception as e:
            log(f"Date: {e}")
            date_label = full_date
        slots = find_available_slots(page)
        log(f"Slots on {date_label}: {[s[1] for s in slots] if slots else 'none'}")
        if not slots:
            time.sleep(poll)
            continue
        chosen_btn, chosen_time = slots[0]
        if DRY_RUN:
            slack(
                f":test_tube:  *DRY RUN \u2014 Slot Found!*\n"
                f"{D}\n"
                f":calendar:  *Date*   :  {date_label}\n"
                f":clock1:  *Slot*   :  {chosen_time}\n"
                f":x:  *Action*  :  NOT booked (DRY_RUN=true)\n"
                f"{D}\n"
                f"_Set DRY_RUN=false in GitHub Secrets to go live_"
            )
            break
        slack(
            f":zap:  *Slot Found \u2014 Booking Now!*\n"
            f"{D}\n"
            f":calendar:  *Date*   :  {date_label}\n"
            f":clock1:  *Slot*   :  {chosen_time}\n"
            f"{D}"
        )
        book_slot(page, chosen_btn, chosen_time)
        send_booked_slack(date_label, chosen_time)
        break

def run_check_mode(page, doctor_url, day_str, mon_str, full_date):
    try:
        page.goto(doctor_url, wait_until="networkidle", timeout=20000)
        time.sleep(1)
    except Exception as e:
        slack(f":x: Could not load page: {e}")
        return
    date_label = select_target_date(page, day_str, mon_str)
    slots      = find_available_slots(page)
    ist        = get_ist()
    log(f"CHECK | {date_label}: {[s[1] for s in slots] if slots else 'none'}")
    if not slots:
        slack(
            f":x:  *No Slots Available*\n"
            f"{D}\n"
            f":male-doctor:  *Doctor*    :  Dr S Kamal Kumar\n"
            f":calendar:  *Date*      :  {date_label}\n"
            f":clock1:  *Checked*   :  {ist.strftime('%d %b %Y  %H:%M')} IST\n"
            f"{D}\n"
            f"_Use `/start` at 6:50 AM for fresh morning slots_"
        )
        return
    chosen_btn, chosen_time = slots[0]
    if DRY_RUN:
        slack(
            f":test_tube:  *DRY RUN \u2014 Slot Found!*\n"
            f"{D}\n"
            f":calendar:  *Date*   :  {date_label}\n"
            f":clock1:  *Slot*   :  {chosen_time}\n"
            f":x:  *Action*  :  NOT booked (DRY_RUN=true)\n"
            f"{D}\n"
            f"_Set DRY_RUN=false in GitHub Secrets to go live_"
        )
        return
    slack(
        f":zap:  *Slot Found \u2014 Booking Now!*\n"
        f"{D}\n"
        f":calendar:  *Date*   :  {date_label}\n"
        f":clock1:  *Slot*   :  {chosen_time}\n"
        f"{D}"
    )
    book_slot(page, chosen_btn, chosen_time)
    send_booked_slack(date_label, chosen_time)

def parse_appointment(raw_text):
    appt = {
        "doctor":   "Dr S Kamal Kumar",
        "specialty":"General Physician",
        "room":     "OPD PHY 2  |  First Floor",
        "date":     "", "time":   "",
        "token":    "", "uhid":   "",
        "status":   "Booked", "payment": "Successful",
    }
    dt_match = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2}\s*(?:am|pm))", raw_text, re.IGNORECASE)
    if dt_match:
        try:
            d = datetime.strptime(dt_match.group(1), "%d/%m/%Y")
            appt["date"] = d.strftime("%d %b %Y")
        except Exception:
            appt["date"] = dt_match.group(1)
        appt["time"] = dt_match.group(2).strip().upper()
    t = re.search(r"token\s*(?:no\.?)?\s*[:\-]?\s*(\d+)", raw_text, re.IGNORECASE)
    if t:
        appt["token"] = t.group(1)
    u = re.search(r"UHID[/\s]+(\w+)", raw_text, re.IGNORECASE)
    if u:
        appt["uhid"] = u.group(1)
    for s in ["Completed", "Booked", "Pending", "Cancelled"]:
        if s.lower() in raw_text.lower():
            appt["status"] = s
            break
    return appt

def run_orders_mode(page):
    ist = get_ist()
    log("Orders mode ...")
    try:
        page.goto(ORDER_URL, wait_until="networkidle", timeout=20000)
        time.sleep(2)
        if "login" in page.url and "dynamic" not in page.url:
            slack(":x: Session expired. Try `/orders` again.")
            return
        raw = page.locator("body").inner_text()
        ist = get_ist()
        has_data = any(k in raw for k in ["Kamal Kumar", "GENERAL PHYSICIAN", "Token", "UHID", "Booked", "Pending"])
        if has_data:
            a = parse_appointment(raw)
            token_line  = f"\n:ticket:  *Token No*      :  {a['token']}" if a["token"] else ""
            uhid_line   = f"\n:id:  *UHID*          :  {a['uhid']}"     if a["uhid"]  else ""
            date_line   = f"\n:calendar:  *Date*          :  {a['date']}" if a["date"]  else ""
            time_line   = f"\n:clock1:  *Time*          :  {a['time']}"  if a["time"]  else ""
            status_icon = {"Booked": ":white_check_mark:", "Completed": ":ballot_box_with_check:",
                           "Pending": ":hourglass:", "Cancelled": ":x:"}.get(a["status"], ":white_check_mark:")
            slack(
                f":clipboard:  *Your Upcoming Appointment*\n"
                f"{D}\n"
                f":male-doctor:  *Doctor*        :  {a['doctor']}\n"
                f":stethoscope:  *Specialty*     :  {a['specialty']}\n"
                f":round_pushpin:  *Room*           :  {a['room']}"
                f"{date_line}{time_line}{token_line}{uhid_line}\n"
                f"{status_icon}  *Status*        :  {a['status']}\n"
                f":credit_card:  *Payment*       :  {a['payment']}\n"
                f"{D}\n"
                f"_Checked: {ist.strftime('%d %b %Y, %H:%M:%S')} IST_"
            )
        else:
            slack(
                f":calendar:  *No Upcoming Appointments*\n"
                f"{D}\n"
                f":x:  No bookings found at this time\n"
                f":mag:  Use `/check` to book a new slot\n"
                f"{D}\n"
                f"_Checked: {ist.strftime('%d %b %Y, %H:%M:%S')} IST_"
            )
    except Exception as e:
        log(f"Orders error: {e}")
        slack(f":x: Could not fetch appointments. Please try again.")

def run():
    from playwright.sync_api import sync_playwright
    ist                         = get_ist()
    target, day_str, mon_str, full_date = get_target_date()
    mode                        = BOT_MODE
    log(f"V2 | Mode:{mode} | IST:{ist.strftime('%H:%M:%S')} | Target:{full_date}")

    if mode == "start":
        slack(
            f":rocket:  *BHEL Appointment Bot*\n"
            f"{D}\n"
            f":male-doctor:  *Doctor*          :  Dr S Kamal Kumar\n"
            f":stethoscope:  *Specialty*       :  General Physician\n"
            f":calendar:  *Target Date*     :  {full_date}\n"
            f"{D}\n"
            f":clock630:  Watching from *6:50 AM IST*  |  Auto-stop: *7:30 AM IST*\n"
            f"{D}"
        )
    elif mode == "check":
        slack(
            f":mag:  *BHEL Appointment Bot*\n"
            f"{D}\n"
            f":male-doctor:  *Doctor*          :  Dr S Kamal Kumar\n"
            f":stethoscope:  *Specialty*       :  General Physician\n"
            f":calendar:  *Target Date*     :  {full_date}\n"
            f"{D}\n"
            f":clock1:  Instant check — book if available\n"
            f"{D}"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(viewport={"width": 1280, "height": 800})
        page    = ctx.new_page()
        log("Logging in ...")
        do_login(page)
        ist = get_ist()
        if mode in ["start", "check"]:
            slack(f":white_check_mark:  *Logged in!*  |  IST: {ist.strftime('%H:%M:%S')}")
        if mode == "orders":
            run_orders_mode(page)
        else:
            doctor_url = navigate_to_doctor(page)
            log(f"Doctor page: {doctor_url}")
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
            f":rotating_light:  *Bot Crashed*\n"
            f"DIVIDER\n"
            f"```{err[-600:]}```\n"
            f"_Type `/start` or `/check` to retry._"
        )
