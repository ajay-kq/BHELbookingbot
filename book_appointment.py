"""
BHEL KarExpert — Booking Bot (Slack + GitHub Actions mode)
Login flow: Click "Login With OTP" → enter 10-digit mobile → Next → enter OTP digits → Login
"""

import os, time, requests, traceback
from datetime import datetime

MOBILE             = os.environ["MOBILE"]
DOCTOR_SEARCH      = os.environ.get("DOCTOR_SEARCH", "Kamal Kumar")
SLACK_WEBHOOK      = os.environ.get("SLACK_WEBHOOK", "")
SLACK_RESPONSE_URL = os.environ.get("SLACK_RESPONSE_URL", "")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "")
DRY_RUN            = os.environ.get("DRY_RUN", "true").lower() == "true"
POLL_INTERVAL      = int(os.environ.get("POLL_INTERVAL", "3600"))
MAX_WAIT_HOURS     = int(os.environ.get("MAX_WAIT_HOURS", "2"))

LOGIN_URL          = "https://bhel.karexpert.com/account-management/login"
AVAILABLE_COLOR    = "rgb(184, 233, 134)"
OTP_POLL_SEC       = 5
OTP_TIMEOUT_SEC    = 120

# Strip country code — portal needs 10-digit number only (e.g. 9876543210)
def get_mobile_10digit():
    m = MOBILE.strip()
    if m.startswith("91") and len(m) == 12:
        return m[2:]   # remove 91 prefix
    if m.startswith("+91"):
        return m[3:]   # remove +91 prefix
    return m           # already 10 digits

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
    print(f"[SLACK] {msg}", flush=True)

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def clear_otp():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        requests.patch(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables/CURRENT_OTP",
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
            json={"name": "CURRENT_OTP", "value": ""},
            timeout=10,
        )
    except Exception:
        pass

def wait_for_otp():
    clear_otp()
    slack(
        "*OTP sent to your phone!* :iphone:\n\n"
        "Please type this in Slack:\n"
        "```/otp 123456```\n"
        "_(replace with your actual OTP — you have 2 minutes)_", ":key:"
    )
    log(f"Waiting up to {OTP_TIMEOUT_SEC}s for OTP ...")
    deadline = time.time() + OTP_TIMEOUT_SEC
    while time.time() < deadline:
        time.sleep(OTP_POLL_SEC)
        try:
            r = requests.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables/CURRENT_OTP",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
                timeout=10,
            )
            if r.status_code == 200:
                val = r.json().get("value", "").strip()
                if val and val.isdigit() and len(val) >= 4:
                    log("OTP received!")
                    clear_otp()
                    return val
        except Exception as e:
            log(f"OTP poll error: {e}")
    return None

def find_available_slots(page):
    all_btns = page.locator("button._wf-pp-timebox")
    available = []
    for i in range(all_btns.count()):
        btn = all_btns.nth(i)
        try:
            style = btn.get_attribute("style") or ""
            if AVAILABLE_COLOR in style and "not-allowed" not in style:
                text = btn.inner_text().strip()
                if text:
                    available.append((btn, text))
        except Exception:
            continue
    return available

def run():
    from playwright.sync_api import sync_playwright

    mobile_10 = get_mobile_10digit()
    log(f"Bot starting | Mobile: {mobile_10[:3]}XXXXXXX | DRY_RUN: {DRY_RUN}")
    slack(f"*Bot initialising...* Opening portal for *Dr S {DOCTOR_SEARCH}*", ":robot_face:")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx  = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()

        # ── Step 1: Open login page ───────────────────────────────────────────
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
        log("Login page loaded")

        # ── Step 2: Click "Login With OTP" ────────────────────────────────────
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
            for tag in ["span", "a", "div", "button"]:
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
            slack(":x: Could not click 'Login With OTP'.")
            raise Exception("Login With OTP not found")

        time.sleep(2)
        log("OTP form visible")

        # ── Step 3: Enter 10-digit mobile number ──────────────────────────────
        log(f"Entering mobile: {mobile_10[:3]}XXXXXXX ...")
        filled = False

        # Portal uses formcontrolname="mob" based on DevTools screenshot
        for selector in [
            'input[formcontrolname="mob"]',
            'input[formcontrolname="mobile"]',
            'input[type="text"]',
            'input[type="tel"]',
            'input[type="number"]',
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.click()
                    el.fill(mobile_10)   # 10-digit only, no country code
                    filled = True
                    log(f"Mobile filled via: {selector}")
                    break
            except Exception:
                continue

        if not filled:
            slack(":x: Could not find mobile input field.")
            raise Exception("Mobile input not found")

        time.sleep(0.5)

        # ── Step 4: Click Next button ─────────────────────────────────────────
        log("Clicking Next ...")
        for selector in ["button.login-button", "button.btn-gradient"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.click()
                    log(f"Clicked Next via: {selector}")
                    break
            except Exception:
                continue
        else:
            for label in ["Next", "Send OTP", "Send", "Continue", "Submit"]:
                try:
                    btn = page.get_by_role("button", name=label, exact=False).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        log(f"Clicked: '{label}'")
                        break
                except Exception:
                    continue

        time.sleep(1.5)

        # ── Step 5: Wait for OTP from Slack ──────────────────────────────────
        otp_code = wait_for_otp()
        if not otp_code:
            slack(":x: OTP timed out (2 min). Type `/book` to restart.", ":hourglass:")
            browser.close()
            return

        # ── Step 6: Enter OTP into 6-box input ───────────────────────────────
        # Portal uses app-otp-input with individual digit boxes
        log(f"Entering OTP: {'*' * len(otp_code)} ...")
        otp_entered = False

        # Method 1: Type into individual input boxes inside app-otp-input
        try:
            otp_inputs = page.locator("app-otp-input input")
            count = otp_inputs.count()
            log(f"Found {count} OTP input boxes")
            if count > 0:
                for i, digit in enumerate(otp_code):
                    if i < count:
                        otp_inputs.nth(i).click()
                        otp_inputs.nth(i).fill(digit)
                        time.sleep(0.1)
                otp_entered = True
                log("OTP entered digit by digit")
        except Exception as e:
            log(f"OTP digit method failed: {e}")

        # Method 2: Find any visible input and type OTP
        if not otp_entered:
            for selector in [
                'input[formcontrolname="otp"]',
                'input[type="number"]',
                'input[maxlength="6"]',
                'input[maxlength="1"]',
            ]:
                try:
                    el = page.locator(selector).first
                    if el.is_visible(timeout=2000):
                        el.fill(otp_code)
                        otp_entered = True
                        log(f"OTP filled via: {selector}")
                        break
                except Exception:
                    continue

        # Method 3: Use keyboard to type OTP after clicking first box
        if not otp_entered:
            try:
                page.locator("app-otp-input").first.click()
                page.keyboard.type(otp_code)
                otp_entered = True
                log("OTP typed via keyboard")
            except Exception as e:
                log(f"Keyboard OTP failed: {e}")

        if not otp_entered:
            slack(":x: Could not enter OTP. Please try again.")
            raise Exception("OTP input failed")

        time.sleep(0.5)

        # ── Step 7: Click Login / Next / Verify ──────────────────────────────
        log("Clicking Login ...")
        for selector in ["button.login-button", "button.btn-gradient"]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.click()
                    log(f"Clicked Login via: {selector}")
                    break
            except Exception:
                continue
        else:
            for label in ["Login", "Next", "Verify", "Submit", "Sign In", "Proceed"]:
                try:
                    btn = page.get_by_role("button", name=label, exact=False).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        log(f"Clicked: '{label}'")
                        break
                except Exception:
                    continue

        page.wait_for_load_state("networkidle", timeout=20000)
        slack(":white_check_mark: Logged in! Navigating to Dr S Kamal Kumar...")
        log("Logged in!")

        # ── Step 8: Book Appointment ──────────────────────────────────────────
        log("Going to Book Appointment ...")
        try:
            page.get_by_role("button", name="Book Appointment").first.click()
        except Exception:
            page.get_by_text("Book Appointment", exact=False).first.click()
        page.wait_for_load_state("networkidle", timeout=20000)

        # ── Step 9: Search doctor ─────────────────────────────────────────────
        log(f"Searching: {DOCTOR_SEARCH} ...")
        try:
            search = page.locator('input[placeholder="Search Doctor"]')
            search.click()
            search.fill(DOCTOR_SEARCH)
            time.sleep(2)
        except Exception as e:
            log(f"Search: {e}")

        # ── Step 10: Click doctor's Book Appointment ──────────────────────────
        log("Clicking doctor's Book Appointment ...")
        try:
            cards = page.locator("kx-search-doctor-list .ng-star-inserted")
            found = False
            for i in range(cards.count()):
                card = cards.nth(i)
                if DOCTOR_SEARCH.split()[0] in (card.inner_text() or ""):
                    card.get_by_text("Book Appointment", exact=False).click()
                    found = True
                    log("Clicked doctor card")
                    break
            if not found:
                raise Exception("Card not found")
        except Exception:
            page.get_by_text("Book Appointment", exact=False).first.click()
        time.sleep(2)

        # ── Step 11: Select furthest date (7th day) ───────────────────────────
        log("Selecting furthest date ...")
        try:
            date_tabs = page.locator("div.dottab")
            total = date_tabs.count()
            if total > 0:
                date_tabs.nth(total - 1).click()
                log(f"Selected date {total}/{total}")
                time.sleep(1.5)
        except Exception as e:
            log(f"Date: {e}")

        booking_url = page.url
        log(f"Booking URL: {booking_url}")

        # ── Step 12: Poll for green slots ─────────────────────────────────────
        max_iter = (MAX_WAIT_HOURS * 3600) // max(POLL_INTERVAL, 60)
        slack(
            f":mag: Checking every *{POLL_INTERVAL//60} hour(s)* for up to *{MAX_WAIT_HOURS} hours*\n"
            f"I'll ping you the moment a slot opens!", ":calendar:"
        )

        for attempt in range(1, max_iter + 1):
            log(f"Attempt {attempt}/{max_iter} ...")
            page.goto(booking_url, wait_until="networkidle", timeout=20000)
            time.sleep(2)

            slots = find_available_slots(page)
            log(f"Green slots: {[s[1] for s in slots] if slots else 'none'}")

            if slots:
                btn, slot_time = slots[0]

                if DRY_RUN:
                    slack(
                        f":test_tube: *[DRY RUN]* Slot: *{slot_time}* — NOT booked (DRY_RUN=true)",
                        ":eyes:"
                    )
                    break

                slack(f":zap: Slot: *{slot_time}* — booking now!", ":tada:")
                btn.click()
                page.wait_for_load_state("networkidle", timeout=15000)
                time.sleep(1)

                confirmed = False
                for label in ["Confirm", "Book", "Submit", "Proceed", "OK", "Yes"]:
                    try:
                        cb = page.get_by_role("button", name=label, exact=False).first
                        if cb.is_visible(timeout=3000):
                            cb.click()
                            page.wait_for_load_state("networkidle", timeout=15000)
                            confirmed = True
                            break
                    except Exception:
                        continue

                now = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
                slack(
                    f"*Appointment Successfully Booked!* :white_check_mark:\n\n"
                    f">  *Doctor:* Dr S Kamal Kumar\n"
                    f">  *Slot:* {slot_time}\n"
                    f">  *Booked at:* {now}\n"
                    f">  *Portal:* bhel.karexpert.com",
                    ":hospital:"
                )
                log("Booked!")
                break

            next_check = datetime.fromtimestamp(time.time() + POLL_INTERVAL).strftime("%H:%M:%S")
            slack(
                f":calendar: *Check {attempt}/{max_iter}:* No open slots.\n"
                f"Next check at *{next_check}*", ":hourglass_flowing_sand:"
            )
            time.sleep(POLL_INTERVAL)

        else:
            slack(f"*No slot found after {MAX_WAIT_HOURS} hours.* Type `/book` to retry.", ":x:")

        browser.close()
        log("Done.")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        err = traceback.format_exc()
        log(f"CRASH:\n{err}")
        slack(
            f"*Bot crashed!* :rotating_light:\n```{err[-800:]}```\n"
            f"_Type `/book` to restart._", ":x:"
        )
