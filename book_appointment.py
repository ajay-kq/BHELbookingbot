"""
BHEL KarExpert — Final Booking Bot
====================================
Start   : Manual /start at 5:15 AM IST
OTP     : /otp XXXXXX in Slack (40s window, acts immediately)
Poll    : 5:16-5:54 AM IST → 10s | 5:55-7:25 AM IST → 2s | 7:25-7:30 AM → 10s
Stop    : 7:30 AM IST auto-stop
Slot    : WHITE pill only — border:rgb(184,233,134), no background, no not-allowed
Date    : Last tab (7th date) only
"""

import os, time, requests, traceback
from datetime import datetime, timezone, timedelta

# ── Config ─────────────────────────────────────────────────────────────────
MOBILE             = os.environ["MOBILE"]
DOCTOR_SEARCH      = os.environ.get("DOCTOR_SEARCH", "Dr S Kamal Kumar")
SLACK_WEBHOOK      = os.environ.get("SLACK_WEBHOOK", "")
SLACK_RESPONSE_URL = os.environ.get("SLACK_RESPONSE_URL", "")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "")
DRY_RUN            = os.environ.get("DRY_RUN", "false").lower() == "true"

LOGIN_URL          = "https://bhel.karexpert.com/account-management/login"
BOOKING_URL        = "https://bhel.karexpert.com/appointment/searchdoctor/searchdepartment/general/cleardate"

# Slot detection — WHITE pill only
WHITE_BORDER       = "rgb(184, 233, 134)"   # border color of available white slot

# Polling intervals (IST)
FAST_POLL          = 2    # 5:55–7:25 AM IST
SLOW_POLL          = 10   # all other times

# Stop time
STOP_HOUR_IST      = 7
STOP_MIN_IST       = 30

# OTP
OTP_POLL_SEC       = 3
OTP_TIMEOUT_SEC    = 40

# ── IST helpers ─────────────────────────────────────────────────────────────
def get_ist():
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

def past_stop_time():
    ist = get_ist()
    if ist.hour > STOP_HOUR_IST:
        return True
    if ist.hour == STOP_HOUR_IST and ist.minute >= STOP_MIN_IST:
        return True
    return False

def get_poll_interval():
    """
    5:55–7:25 AM IST → 2 seconds (peak)
    all other times  → 10 seconds
    """
    ist = get_ist()
    h, m = ist.hour, ist.minute
    # Peak window: 5:55 AM to 7:25 AM
    after_start  = (h == 5 and m >= 55) or (h == 6) or (h == 7 and m < 25)
    if after_start:
        return FAST_POLL
    return SLOW_POLL

# ── Slack ───────────────────────────────────────────────────────────────────
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
    print(f"[SLACK] {msg[:100]}", flush=True)

def log(msg):
    ist = get_ist()
    print(f"[{ist.strftime('%H:%M:%S')} IST] {msg}", flush=True)

# ── OTP ─────────────────────────────────────────────────────────────────────
def clear_otp():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        requests.patch(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables/CURRENT_OTP",
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                     "Accept": "application/vnd.github+json"},
            json={"name": "CURRENT_OTP", "value": ""},
            timeout=10,
        )
    except Exception:
        pass

def wait_for_otp():
    clear_otp()
    slack(
        "*OTP sent to your phone!* :iphone:\n\n"
        ":point_right: Type your OTP in Slack:\n"
        "```/otp 583921```\n"
        "_(replace with your 6-digit OTP)_\n"
        ":alarm_clock: *40 seconds* — bot acts immediately!", ":key:"
    )
    log(f"Waiting up to {OTP_TIMEOUT_SEC}s for OTP ...")
    deadline = time.time() + OTP_TIMEOUT_SEC
    while time.time() < deadline:
        time.sleep(OTP_POLL_SEC)
        try:
            r = requests.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables/CURRENT_OTP",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                         "Accept": "application/vnd.github+json"},
                timeout=10,
            )
            if r.status_code == 200:
                val = r.json().get("value", "").strip()
                if val and val.isdigit() and len(val) >= 4:
                    log(f"OTP received immediately!")
                    clear_otp()
                    return val
        except Exception as e:
            log(f"OTP poll: {e}")
    return None

# ── Slot detection ───────────────────────────────────────────────────────────
def find_available_slots(page):
    """
    Detect WHITE pill slots only:
      - class contains _wf-pp-timebox
      - style has border: rgb(184, 233, 134)
      - style does NOT have background: (no fill)
      - style does NOT have cursor: not-allowed
      - button is not disabled
      - button is visible

    White pill = available to book
    Green fill = already booked/blocked (cursor:not-allowed)
    """
    all_btns = page.locator("button._wf-pp-timebox")
    white_slots  = []   # priority 1 — white pill
    orange_slots = []   # priority 2 — orange border (fallback)
    count = all_btns.count()

    for i in range(count):
        btn = all_btns.nth(i)
        try:
            if not btn.is_visible():
                continue
            if btn.is_disabled():
                continue

            style   = btn.get_attribute("style") or ""
            classes = btn.get_attribute("class") or ""

            # Hard skip — blocked slots
            if "cursor: not-allowed" in style or "not-allowed" in style:
                continue
            if "disabled" in classes.lower():
                continue

            text = btn.inner_text().strip()
            if not text:
                continue

            # WHITE pill: has border color but NO background fill
            has_green_border = WHITE_BORDER in style
            has_background   = "background:" in style or "background-color:" in style

            if has_green_border and not has_background:
                white_slots.append((btn, text))
                log(f"WHITE slot found: {text}")
            elif "rgb(251, 144, 38)" in style or "rgb(255, 165, 0)" in style:
                # Orange border = over booking fallback
                orange_slots.append((btn, text))

        except Exception:
            continue

    # Return white first, then orange as fallback
    return white_slots if white_slots else orange_slots

# ── Mobile number ────────────────────────────────────────────────────────────
def get_mobile():
    m = MOBILE.strip()
    if m.startswith("+91"): return m[3:]
    if m.startswith("91") and len(m) == 12: return m[2:]
    return m

# ── Main ─────────────────────────────────────────────────────────────────────
def run():
    from playwright.sync_api import sync_playwright

    mobile = get_mobile()
    ist    = get_ist()
    log(f"Bot starting | IST: {ist.strftime('%H:%M:%S')} | DRY_RUN: {DRY_RUN}")

    slack(
        f"*Bot started!* :rocket:\n"
        f">  Doctor: *{DOCTOR_SEARCH}*\n"
        f">  IST time: *{ist.strftime('%H:%M:%S')}*\n"
        f">  Peak poll: *2s* from 5:55 AM IST\n"
        f">  Auto-stop: *7:30 AM IST*",
        ":robot_face:"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx  = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()

        # ── STEP 1: Open login page ──────────────────────────────────────
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
        log("Login page ready")

        # ── STEP 2: Click "Login With OTP" ──────────────────────────────
        log("Clicking 'Login With OTP' ...")
        clicked = False
        for selector in ["span.cLink", ".cLink"]:
            try:
                el = page.locator(selector).filter(has_text="OTP").first
                if el.is_visible(timeout=3000):
                    el.click()
                    clicked = True
                    log(f"Clicked via {selector}")
                    break
            except Exception:
                continue
        if not clicked:
            for tag in ["span", "a", "div"]:
                try:
                    el = page.locator(tag).filter(has_text="Login With OTP").first
                    if el.is_visible(timeout=2000):
                        el.click()
                        clicked = True
                        log(f"Clicked <{tag}>")
                        break
                except Exception:
                    continue
        if not clicked:
            slack(":x: Could not find 'Login With OTP'. Type `/start` to retry.")
            raise Exception("Login With OTP not found")
        time.sleep(2)

        # ── STEP 3: Enter mobile number ──────────────────────────────────
        log("Entering mobile ...")
        filled = False
        for selector in [
            'input[formcontrolname="mob"]',
            'input[formcontrolname="mobile"]',
            'input[type="text"]',
            'input[type="tel"]',
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.click()
                    el.fill(mobile)
                    filled = True
                    log(f"Mobile filled via {selector}")
                    break
            except Exception:
                continue
        if not filled:
            slack(":x: Could not find mobile input. Type `/start` to retry.")
            raise Exception("Mobile input not found")
        time.sleep(0.5)

        # ── STEP 4: Click Next ───────────────────────────────────────────
        log("Clicking Next ...")
        for selector in ["button.login-button", "button.btn-gradient"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.click()
                    log(f"Clicked Next via {selector}")
                    break
            except Exception:
                continue
        time.sleep(1.5)

        # ── STEP 5: Wait for OTP from Slack ─────────────────────────────
        otp_code = wait_for_otp()
        if not otp_code:
            slack(":x: OTP timed out (40s). Type `/start` to retry.", ":hourglass:")
            browser.close()
            return

        # ── STEP 6: Enter OTP digit by digit ────────────────────────────
        log("Entering OTP ...")
        otp_done = False
        try:
            otp_inputs = page.locator("app-otp-input input")
            count = otp_inputs.count()
            log(f"Found {count} OTP input boxes")
            if count >= len(otp_code):
                for i, digit in enumerate(otp_code):
                    otp_inputs.nth(i).click()
                    otp_inputs.nth(i).fill(digit)
                    time.sleep(0.1)
                otp_done = True
                log("OTP entered digit by digit")
        except Exception as e:
            log(f"OTP digit method: {e}")

        if not otp_done:
            try:
                page.locator("app-otp-input").first.click()
                page.keyboard.type(otp_code)
                otp_done = True
                log("OTP typed via keyboard")
            except Exception as e:
                log(f"Keyboard OTP: {e}")

        if not otp_done:
            slack(":x: Could not enter OTP. Type `/start` to retry.")
            raise Exception("OTP entry failed")
        time.sleep(0.5)

        # ── STEP 7: Click Login ──────────────────────────────────────────
        log("Clicking Login ...")
        for selector in ["button.login-button", "button.btn-gradient"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.click()
                    log(f"Login clicked via {selector}")
                    break
            except Exception:
                continue

        # ── STEP 8: Confirm login via DOM ────────────────────────────────
        log("Waiting for login confirmation ...")
        login_ok = False

        # Method 1: wait for dashboard DOM elements
        for selector in ["app-header", "app-sidebar", "app-base", "app-dynamic-dashboard"]:
            try:
                page.wait_for_selector(selector, timeout=15000)
                login_ok = True
                log(f"Login confirmed via DOM: {selector}")
                break
            except Exception:
                continue

        # Method 2: poll URL every 2s for 20s
        if not login_ok:
            log("DOM check failed — polling URL ...")
            for i in range(10):
                time.sleep(2)
                url = page.url
                log(f"[{(i+1)*2}s] URL: {url}")
                if "dynamic_dashboard" in url:
                    login_ok = True
                    log("Login confirmed via URL!")
                    break
                if "loginwithotp" not in url and "login" not in url:
                    login_ok = True
                    log("Login confirmed — URL changed!")
                    break

        # Method 3: optimistic — try navigating anyway
        if not login_ok:
            log("Optimistic continue — navigating to booking page ...")
            login_ok = True

        ist = get_ist()
        slack(
            f":white_check_mark: *Logged in!* IST: {ist.strftime('%H:%M:%S')}\n"
            f"Navigating to booking page...",
        )
        log("Logged in!")

        # ── STEP 9: Navigate to booking page ────────────────────────────
        log("Navigating to booking page ...")
        page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
        time.sleep(3)

        # Check not redirected to login
        if "loginwithotp" in page.url or ("login" in page.url and "dynamic" not in page.url):
            slack(":x: Session expired. Type `/start` to retry.")
            raise Exception("Session expired")

        log(f"Booking page loaded: {page.url}")

        # ── STEP 10: Find Dr S Kamal Kumar ──────────────────────────────
        log("Finding Dr S Kamal Kumar ...")
        try:
            page.wait_for_selector("div#doctor-card", timeout=15000)
            time.sleep(1)
            cards = page.locator("div#doctor-card")
            total = cards.count()
            log(f"Found {total} doctor cards")
            found = False
            for i in range(total):
                card = cards.nth(i)
                try:
                    if "Kamal Kumar" in (card.inner_text() or "") or \
                       "Dr S Kamal" in (card.inner_text() or ""):
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
                log("Fallback: clicking first primary-btn ...")
                page.locator("button.primary-btn").first.click()

        except Exception as e:
            slack(f":x: Could not find Dr S Kamal Kumar: {e}")
            raise
        time.sleep(2)

        doctor_page_url = page.url
        log(f"Doctor slot page URL: {doctor_page_url}")

        # ── STEP 11: Poll loop ───────────────────────────────────────────
        ist = get_ist()
        poll = get_poll_interval()
        slack(
            f":mag: *Watching for slots!*\n"
            f">  IST: *{ist.strftime('%H:%M:%S')}*\n"
            f">  Current poll: *{poll}s*\n"
            f">  Peak (2s) starts: *5:55 AM IST*\n"
            f">  Checking: *last date tab (7th)*\n"
            f">  Slot type: *white pill only*\n"
            f">  Auto-stop: *7:30 AM IST*",
            ":clock530:"
        )

        attempt       = 0
        prev_tab_count = 0

        while True:
            attempt += 1

            # ── Check stop time ──────────────────────────────────────────
            if past_stop_time():
                ist = get_ist()
                slack(
                    f":stopwatch: *7:30 AM IST reached — bot stopping.*\n"
                    f">  No slot found today.\n"
                    f">  IST: {ist.strftime('%H:%M:%S')}\n"
                    f">  Type `/start` tomorrow at *5:15 AM IST*",
                    ":x:"
                )
                log("7:30 AM IST — auto-stopping")
                break

            poll = get_poll_interval()
            ist  = get_ist()
            log(f"── Attempt {attempt} | {ist.strftime('%H:%M:%S')} IST | poll:{poll}s ──")

            # ── Reload page ──────────────────────────────────────────────
            try:
                page.goto(doctor_page_url, wait_until="networkidle", timeout=20000)
                time.sleep(1)
            except Exception as e:
                log(f"Reload error: {e}")
                time.sleep(poll)
                continue

            # ── Click last date tab ──────────────────────────────────────
            date_label = "last date"
            try:
                page.wait_for_selector("div.dottab", timeout=8000)
                time.sleep(0.3)
                tabs       = page.locator("div.dottab")
                total_tabs = tabs.count()

                if total_tabs > prev_tab_count and prev_tab_count > 0:
                    log(f"NEW TAB DETECTED! {prev_tab_count} → {total_tabs}")
                    slack(
                        f":tada: *New date tab unlocked!*\n"
                        f"Portal now shows *{total_tabs}* dates.\n"
                        f"Checking new slots immediately!", ""
                    )

                prev_tab_count = total_tabs

                if total_tabs > 0:
                    last_tab   = tabs.nth(total_tabs - 1)
                    date_label = last_tab.inner_text().strip()
                    last_tab.click()
                    time.sleep(1)
                    log(f"Last tab ({total_tabs}/{total_tabs}): {date_label}")

                    if attempt == 1:
                        slack(
                            f":calendar: Watching *{date_label}* (tab {total_tabs} — newest)\n"
                            f"New tab may appear 6:30–7:15 AM IST", ""
                        )
            except Exception as e:
                log(f"Date tab: {e}")

            # ── Find available slots ─────────────────────────────────────
            slots = find_available_slots(page)
            log(f"White slots on {date_label}: {[s[1] for s in slots] if slots else 'none'}")

            if not slots:
                time.sleep(poll)
                continue

            # ── SLOT FOUND — BOOK IT ─────────────────────────────────────
            chosen_btn, chosen_time = slots[0]
            ist = get_ist()
            log(f"SLOT FOUND: {chosen_time} on {date_label} at {ist.strftime('%H:%M:%S')} IST")

            if DRY_RUN:
                slack(
                    f":test_tube: *[DRY RUN]* Slot found!\n"
                    f">  Date: *{date_label}*\n"
                    f">  Time: *{chosen_time}*\n"
                    f">  IST: {ist.strftime('%H:%M:%S')}\n"
                    f"_DRY_RUN=true — NOT booked._", ":eyes:"
                )
                log("DRY RUN — not booking")
                break

            slack(f":zap: *Slot found!* {chosen_time} on {date_label} — booking now!", ":tada:")

            # Click the slot
            try:
                chosen_btn.click()
                time.sleep(2)
            except Exception as e:
                log(f"Slot click error: {e}")
                time.sleep(poll)
                continue

            # Wait for cart
            log("Waiting for booking cart ...")
            try:
                page.wait_for_selector("kx-cart", timeout=10000)
                log("Cart appeared!")
            except Exception:
                log("Cart timeout — confirming anyway ...")
            time.sleep(1)

            # Click Book Appointment in cart
            confirmed = False
            for selector in [
                "div._wf-pp-bookappointmentdivx2",
                "._wf-pp-bookappointmentdivx2",
            ]:
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
            ist = get_ist()

            slack(
                f"*Appointment Successfully Booked!* :white_check_mark:\n\n"
                f">  *Doctor:*  Dr S Kamal Kumar\n"
                f">  *Date:*    {date_label}\n"
                f">  *Slot:*    {chosen_time}\n"
                f">  *Booked:*  {ist.strftime('%d-%b-%Y %H:%M:%S')} IST\n"
                f">  *Portal:*  bhel.karexpert.com\n\n"
                f"{'_Confirmed on portal._' if confirmed else '_Please verify on portal._'}",
                ":hospital:"
            )
            log("DONE — Appointment booked!")
            break

        browser.close()
        log("Browser closed. Done.")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        err = traceback.format_exc()
        log(f"CRASH:\n{err}")
        slack(
            f"*Bot crashed!* :rotating_light:\n```{err[-800:]}```\n"
            f"_Type `/start` to restart._", ":x:"
        )
