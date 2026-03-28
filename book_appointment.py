"""
BHEL KarExpert — Final Booking Bot
===================================
Start  : Manual /start from Slack at 6:25 AM
OTP    : /otp command → Slack asks → you type 6 digits → Enter
Poll   : Every 30 seconds on last (7th) date tab
Stop   : Auto-stops at 7:20 AM or when booking confirmed
Slots  : Any available slot (not gray, not cursor:not-allowed)
"""

import os, time, requests, traceback
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
MOBILE             = os.environ["MOBILE"]
DOCTOR_SEARCH      = os.environ.get("DOCTOR_SEARCH", "Kamal Kumar")
SLACK_WEBHOOK      = os.environ.get("SLACK_WEBHOOK", "")
SLACK_RESPONSE_URL = os.environ.get("SLACK_RESPONSE_URL", "")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "")
DRY_RUN            = os.environ.get("DRY_RUN", "false").lower() == "true"

LOGIN_URL          = "https://bhel.karexpert.com/account-management/login"
BOOKING_URL        = "https://bhel.karexpert.com/appointment/searchdoctor/searchdepartment/general/cleardate"

POLL_INTERVAL_SEC  = 30      # poll every 30 seconds
STOP_HOUR          = 7       # auto-stop hour
STOP_MIN           = 20      # auto-stop minute (7:20 AM)
OTP_POLL_SEC       = 3
OTP_TIMEOUT_SEC    = 120

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_mobile():
    m = MOBILE.strip()
    if m.startswith("+91"): return m[3:]
    if m.startswith("91") and len(m) == 12: return m[2:]
    return m

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

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
    log(f"[SLACK] {msg[:80]}")

def past_stop_time():
    now = datetime.now()
    return now.hour > STOP_HOUR or (now.hour == STOP_HOUR and now.minute >= STOP_MIN)

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
    """Wait for user to type /otp XXXXXX in Slack."""
    clear_otp()
    slack(
        "*OTP sent to your phone!* :iphone:\n\n"
        "Please type your 6-digit OTP in Slack:\n"
        "```/otp 583921```\n"
        "_(replace 583921 with your actual OTP)_\n"
        "You have 2 minutes.", ":key:"
    )
    log(f"Waiting up to {OTP_TIMEOUT_SEC}s for OTP from Slack ...")
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
                    log(f"OTP received: {'*' * len(val)}")
                    clear_otp()
                    return val
        except Exception as e:
            log(f"OTP poll: {e}")
    return None

def find_available_slots(page):
    """
    Find all bookable slot buttons.

    Slot appearance from portal screenshots:
      - Available : white/light pill with dark text, no cursor:not-allowed
      - Green pill : rgb(184,233,134) — also bookable
      - Blocked   : cursor:not-allowed OR class contains disabled

    Strategy: grab ALL visible _wf-pp-timebox buttons,
    skip only the ones that are explicitly blocked.
    """
    all_btns = page.locator("button._wf-pp-timebox")
    available = []
    count = all_btns.count()

    for i in range(count):
        btn = all_btns.nth(i)
        try:
            # Must be visible
            if not btn.is_visible():
                continue

            style   = btn.get_attribute("style") or ""
            classes = btn.get_attribute("class") or ""

            # Skip explicitly blocked slots
            if "not-allowed" in style:
                continue
            if "cursor: not-allowed" in style:
                continue
            if "disabled" in classes.lower():
                continue
            if btn.is_disabled():
                continue

            text = btn.inner_text().strip()
            if text:
                available.append((btn, text))
        except Exception:
            continue

    return available

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    from playwright.sync_api import sync_playwright

    mobile = get_mobile()
    log(f"Bot starting | Mobile: {mobile[:3]}XXXXXXX | DRY_RUN: {DRY_RUN}")
    slack(
        f"*Bot started!* :rocket:\n"
        f"Opening portal for *Dr S {DOCTOR_SEARCH}*\n"
        f"Will poll every *{POLL_INTERVAL_SEC}s* until *7:20 AM*",
        ":robot_face:"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx  = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()

        # ── STEP 1: Open login page ───────────────────────────────────────────
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

        # ── STEP 2: Click "Login With OTP" ───────────────────────────────────
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

        # ── STEP 3: Enter mobile number ───────────────────────────────────────
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

        # ── STEP 4: Click Next ────────────────────────────────────────────────
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

        # ── STEP 5: Wait for OTP from Slack ──────────────────────────────────
        otp_code = wait_for_otp()
        if not otp_code:
            slack(
                ":hourglass: *OTP timed out* (2 min).\n"
                "Type `/start` to restart.", ":x:"
            )
            browser.close()
            return

        # ── STEP 6: Enter OTP digit by digit into 6-box input ────────────────
        log(f"Entering OTP ({'*' * len(otp_code)}) ...")
        otp_done = False

        # Method 1: find individual input boxes inside app-otp-input
        try:
            otp_inputs = page.locator("app-otp-input input")
            count = otp_inputs.count()
            log(f"Found {count} OTP input boxes")
            if count >= len(otp_code):
                for i, digit in enumerate(otp_code):
                    otp_inputs.nth(i).click()
                    otp_inputs.nth(i).fill(digit)
                    time.sleep(0.15)
                otp_done = True
                log("OTP entered digit by digit")
        except Exception as e:
            log(f"OTP box method: {e}")

        # Method 2: click component and type
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

        # ── STEP 7: Click Login ───────────────────────────────────────────────
        log("Clicking Login ...")
        for selector in ["button.login-button", "button.btn-gradient"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.click()
                    log(f"Login via {selector}")
                    break
            except Exception:
                continue
        page.wait_for_load_state("networkidle", timeout=20000)
        slack(":white_check_mark: *Logged in!* Navigating to booking page...")
        log("Logged in!")

        # ── STEP 8: Go to booking page ────────────────────────────────────────
        log("Navigating to booking page ...")
        page.goto(BOOKING_URL, wait_until="networkidle", timeout=30000)
        time.sleep(3)

        # Wait for page to fully render — try multiple indicators
        for selector in [
            'input[placeholder="Search Doctor"]',
            "kx-search-doctor-list",
            "div#doctor-card",
            "._wf-pp-maindiv",
        ]:
            try:
                page.wait_for_selector(selector, timeout=8000)
                log(f"Page ready — found: {selector}")
                break
            except Exception:
                continue
        time.sleep(2)
        log("Booking page loaded")

        # ── STEP 9: Search for Dr Kamal Kumar ─────────────────────────────────
        log(f"Searching: {DOCTOR_SEARCH} ...")
        search_done = False

        # Try search box
        for attempt in range(3):
            try:
                search = page.locator('input[placeholder="Search Doctor"]')
                if search.is_visible(timeout=5000):
                    search.click()
                    search.fill(DOCTOR_SEARCH)
                    time.sleep(2)
                    search_done = True
                    log("Search filled")
                    break
            except Exception as e:
                log(f"Search attempt {attempt+1}: {e}")
                time.sleep(2)

        if not search_done:
            log("Search box not found — doctor list may already be showing")

        # Wait for doctor cards
        try:
            page.wait_for_selector("div#doctor-card", timeout=15000)
            time.sleep(1)
            log("Doctor cards visible")
        except Exception:
            log("Doctor cards timeout — trying anyway")

        # ── STEP 10: Click Book Appointment on Dr Kamal Kumar's card ──────────
        log("Finding Dr S Kamal Kumar ...")
        found_doctor = False

        # Try multiple card selectors
        for card_selector in ["div#doctor-card", "div._wf-pp-divforcard", "kx-search-doctor-list .ng-star-inserted"]:
            try:
                cards = page.locator(card_selector)
                total = cards.count()
                log(f"Selector '{card_selector}': {total} cards")

                if total == 0:
                    continue

                for i in range(total):
                    card = cards.nth(i)
                    try:
                        card_text = card.inner_text() or ""
                        if "Kamal" in card_text or DOCTOR_SEARCH.split()[0] in card_text:
                            log(f"Found Dr Kamal Kumar at card {i+1}")
                            card.scroll_into_view_if_needed()
                            time.sleep(0.5)
                            # Try primary-btn first
                            for btn_sel in ["button.primary-btn", "button.primary-btn.disabledBookBtn", "button[class*='primary']"]:
                                try:
                                    btn = card.locator(btn_sel).first
                                    if btn.is_visible(timeout=3000):
                                        btn.click()
                                        found_doctor = True
                                        log(f"Clicked via {btn_sel}")
                                        break
                                except Exception:
                                    continue
                            if found_doctor:
                                break
                    except Exception as e:
                        log(f"Card {i+1}: {e}")

                if found_doctor:
                    break
            except Exception as e:
                log(f"Card selector '{card_selector}': {e}")

        if not found_doctor:
            # Last resort: take a screenshot hint and click first visible primary-btn
            log("Last resort: clicking first visible primary-btn on page ...")
            try:
                btns = page.locator("button.primary-btn")
                count = btns.count()
                log(f"Found {count} primary-btn buttons total")
                for i in range(count):
                    try:
                        btn = btns.nth(i)
                        if btn.is_visible(timeout=2000):
                            btn_text = btn.inner_text().strip()
                            log(f"Button {i+1}: '{btn_text}'")
                            if "Book" in btn_text or "Appointment" in btn_text:
                                btn.click()
                                found_doctor = True
                                log(f"Clicked button: '{btn_text}'")
                                break
                    except Exception:
                        continue
                if not found_doctor and count > 0:
                    btns.first.click()
                    found_doctor = True
                    log("Clicked first primary-btn")
            except Exception as e:
                slack(f":x: Cannot find Book Appointment button: {e}")
                raise Exception(f"Book button not found: {e}")

        time.sleep(2)

        # Save doctor slot page URL for polling
        doctor_page_url = page.url
        log(f"Doctor page URL: {doctor_page_url}")

        slack(
            f":mag: *Watching for slots every {POLL_INTERVAL_SEC} seconds*\n"
            f"Checking last date tab only\n"
            f"Bot auto-stops at *7:20 AM*\n"
            f"I'll book the first available slot immediately!", ":clock630:"
        )

        # ── STEP 11: Poll every 30 seconds until 7:20 AM ─────────────────────
        attempt = 0
        while True:
            attempt += 1

            # Check stop time
            if past_stop_time():
                slack(
                    ":stopwatch: *7:20 AM reached — bot stopping.*\n"
                    "No slot was found today.\n"
                    "Type `/start` tomorrow at 6:25 AM to try again.",
                    ":x:"
                )
                log("7:20 AM — stopping")
                break

            log(f"── Attempt {attempt} | {datetime.now().strftime('%H:%M:%S')} ──")

            # Reload page
            try:
                page.goto(doctor_page_url, wait_until="networkidle", timeout=20000)
                time.sleep(1.5)
            except Exception as e:
                log(f"Reload error: {e}")
                time.sleep(POLL_INTERVAL_SEC)
                continue

            # Click LAST date tab
            date_label = "last date"
            try:
                tabs = page.locator("div.dottab")
                total_tabs = tabs.count()
                if total_tabs > 0:
                    last_tab = tabs.nth(total_tabs - 1)
                    date_label = last_tab.inner_text().strip()
                    last_tab.click()
                    time.sleep(1.5)
                    log(f"Clicked last tab ({total_tabs}/{total_tabs}): {date_label}")
            except Exception as e:
                log(f"Date tab: {e}")

            # Find available slots
            slots = find_available_slots(page)
            log(f"Available slots on {date_label}: {[s[1] for s in slots] if slots else 'none'}")

            if not slots:
                log(f"No slots. Waiting {POLL_INTERVAL_SEC}s ...")
                time.sleep(POLL_INTERVAL_SEC)
                continue

            # ── SLOT FOUND → BOOK IT ──────────────────────────────────────────
            chosen_btn, chosen_time = slots[0]
            log(f"SLOT FOUND: {chosen_time} on {date_label}")

            if DRY_RUN:
                slack(
                    f":test_tube: *[DRY RUN]* Slot found!\n"
                    f">  Date: *{date_label}*\n"
                    f">  Time: *{chosen_time}*\n"
                    f"_DRY_RUN=true — NOT booked._", ":eyes:"
                )
                log("DRY RUN — not booking")
                break

            slack(f":zap: *Slot found!* {chosen_time} on {date_label} — booking now!", ":tada:")

            # Click the slot button
            try:
                chosen_btn.click()
                time.sleep(2)
            except Exception as e:
                log(f"Slot click error: {e}")
                time.sleep(POLL_INTERVAL_SEC)
                continue

            # Wait for booking cart to appear
            log("Waiting for cart ...")
            try:
                page.wait_for_selector("kx-cart", timeout=10000)
                log("Cart appeared")
            except Exception:
                log("Cart not detected — trying to confirm anyway")
            time.sleep(1)

            # Click "Book Appointment ✓" in cart
            confirmed = False

            # Primary: exact class from DevTools
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

            # Fallback
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
            now_str = datetime.now().strftime("%d-%b-%Y %H:%M:%S")

            slack(
                f"*Appointment Successfully Booked!* :white_check_mark:\n\n"
                f">  *Doctor:*  Dr S Kamal Kumar\n"
                f">  *Date:*    {date_label}\n"
                f">  *Slot:*    {chosen_time}\n"
                f">  *Booked:*  {now_str}\n"
                f">  *Portal:*  bhel.karexpert.com\n\n"
                f"{'_Confirmed on portal._' if confirmed else '_Please verify on portal manually._'}",
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
