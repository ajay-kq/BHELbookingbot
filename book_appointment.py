"""
============================================================
  BHEL KarExpert — Booking Bot (Slack + GitHub Actions mode)
  Login flow: Login With OTP → phone number → Next → OTP → Login
============================================================
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
    log(f"Waiting up to {OTP_TIMEOUT_SEC}s for OTP from Slack ...")
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

    log("Bot starting")
    slack(f"*Bot initialising...* Opening portal for *Dr S {DOCTOR_SEARCH}*", ":robot_face:")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx  = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()

        # ── Step 1: Open login page ───────────────────────────────────────────
        log("Opening login page ...")
        page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)

        # Wait for spinner + form
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

        # ── Step 2: Click "Login With OTP" to switch form mode ───────────────
        log("Clicking 'Login With OTP' ...")
        clicked = False

        # Try span.cLink first (exact from DevTools)
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

        # Fallback: any element with the text
        if not clicked:
            for tag in ["span", "a", "div", "button"]:
                try:
                    el = page.locator(tag).filter(has_text="Login With OTP").first
                    if el.is_visible(timeout=2000):
                        el.click()
                        clicked = True
                        log(f"Clicked <{tag}> Login With OTP")
                        break
                except Exception:
                    continue

        if not clicked:
            try:
                page.get_by_text("Login With OTP", exact=False).first.click()
                clicked = True
                log("Clicked via get_by_text")
            except Exception:
                pass

        if not clicked:
            slack(":x: Could not click 'Login With OTP'. Portal may have changed.")
            raise Exception("Login With OTP not found")

        # Wait for phone number input to appear
        time.sleep(2)
        log("OTP login form should now be visible")

        # ── Step 3: Enter mobile number ───────────────────────────────────────
        log("Entering mobile number ...")
        filled = False
        for selector in [
            'input[formcontrolname="mobile"]',
            'input[type="tel"]',
            'input[type="number"][maxlength="10"]',
            'input[placeholder*="obile" i]',
            'input[placeholder*="hone" i]',
            'input[formcontrolname="login_id"]',
            'input[type="text"]',
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.click()
                    el.fill(MOBILE)
                    filled = True
                    log(f"Mobile filled via: {selector}")
                    break
            except Exception:
                continue

        if not filled:
            slack(":x: Could not find mobile number input.")
            raise Exception("Mobile input not found")

        time.sleep(0.5)

        # ── Step 4: Click Next / Send OTP button ─────────────────────────────
        log("Clicking Next / Send OTP ...")
        for label in ["Next", "Send OTP", "Get OTP", "Send", "Continue", "Submit", "Proceed"]:
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

        # ── Step 6: Enter OTP ─────────────────────────────────────────────────
        log("Entering OTP ...")
        otp_filled = False
        for selector in [
            'input[formcontrolname="otp"]',
            'input[type="number"]',
            'input[maxlength="6"]',
            'input[maxlength="4"]',
            'input[placeholder*="otp" i]',
            'input[placeholder*="OTP" i]',
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.fill(otp_code)
                    otp_filled = True
                    log(f"OTP entered via: {selector}")
                    break
            except Exception:
                continue

        if not otp_filled:
            slack(":x: Could not find OTP input field.")
            raise Exception("OTP input not found")

        time.sleep(0.5)

        # ── Step 7: Click Login / Verify ──────────────────────────────────────
        log("Clicking Login / Verify ...")
        for label in ["Login", "Verify", "Submit", "Verify OTP", "Sign In", "Proceed", "Confirm"]:
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
        log("Logged in successfully!")

        # ── Step 8: Book Appointment section ──────────────────────────────────
        log("Navigating to Book Appointment ...")
        try:
            page.get_by_role("button", name="Book Appointment").first.click()
        except Exception:
            page.get_by_text("Book Appointment", exact=False).first.click()
        page.wait_for_load_state("networkidle", timeout=20000)

        # ── Step 9: Search for doctor ─────────────────────────────────────────
        log(f"Searching for: {DOCTOR_SEARCH} ...")
        try:
            search = page.locator('input[placeholder="Search Doctor"]')
            search.click()
            search.fill(DOCTOR_SEARCH)
            time.sleep(2)
        except Exception as e:
            log(f"Search box: {e}")

        # ── Step 10: Click Book Appointment on Dr Kamal Kumar's card ──────────
        log("Clicking doctor's Book Appointment ...")
        try:
            cards = page.locator("kx-search-doctor-list .ng-star-inserted")
            found = False
            for i in range(cards.count()):
                card = cards.nth(i)
                if DOCTOR_SEARCH.split()[0] in (card.inner_text() or ""):
                    card.get_by_text("Book Appointment", exact=False).click()
                    found = True
                    log("Clicked doctor card Book Appointment")
                    break
            if not found:
                raise Exception("Doctor card not matched")
        except Exception:
            log("Fallback: clicking first Book Appointment")
            page.get_by_text("Book Appointment", exact=False).first.click()
        time.sleep(2)

        # ── Step 11: Select furthest available date ────────────────────────────
        log("Selecting furthest date ...")
        try:
            date_tabs = page.locator("div.dottab")
            total = date_tabs.count()
            if total > 0:
                date_tabs.nth(total - 1).click()
                log(f"Selected date {total}/{total}")
                time.sleep(1.5)
        except Exception as e:
            log(f"Date selection: {e}")

        booking_url = page.url
        log(f"Booking URL: {booking_url}")

        # ── Step 12: Poll every hour for green slots ───────────────────────────
        max_iter = (MAX_WAIT_HOURS * 3600) // max(POLL_INTERVAL, 60)
        slack(
            f":mag: Checking every *{POLL_INTERVAL//60} hour(s)* for up to *{MAX_WAIT_HOURS} hours*\n"
            f"Will ping you the moment a green slot opens!", ":calendar:"
        )

        for attempt in range(1, max_iter + 1):
            log(f"Attempt {attempt}/{max_iter} — refreshing page ...")
            page.goto(booking_url, wait_until="networkidle", timeout=20000)
            time.sleep(2)

            slots = find_available_slots(page)
            log(f"Green slots found: {[s[1] for s in slots] if slots else 'none'}")

            if slots:
                btn, slot_time = slots[0]

                if DRY_RUN:
                    slack(
                        f":test_tube: *[DRY RUN]* Slot found: *{slot_time}*\n"
                        f"Doctor: Dr S Kamal Kumar\n"
                        f"_DRY_RUN=true — NOT booked. Set to false in workflow to go live._",
                        ":eyes:"
                    )
                    log("DRY RUN — not booking")
                    break

                slack(f":zap: Slot found: *{slot_time}* — booking now!", ":tada:")
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
                            log(f"Confirmed via: '{label}'")
                            break
                    except Exception:
                        continue

                now = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
                slack(
                    f"*Appointment Successfully Booked!* :white_check_mark:\n\n"
                    f">  *Doctor:* Dr S Kamal Kumar\n"
                    f">  *Slot:* {slot_time}\n"
                    f">  *Booked at:* {now}\n"
                    f">  *Portal:* bhel.karexpert.com\n\n"
                    f"{'Confirmed by portal.' if confirmed else 'Please verify on portal.'}",
                    ":hospital:"
                )
                log("Appointment booked!")
                break

            next_check = datetime.fromtimestamp(time.time() + POLL_INTERVAL).strftime("%H:%M:%S")
            slack(
                f":calendar: *Check {attempt}/{max_iter}:* No open slots for Dr S Kamal Kumar.\n"
                f"Next check at *{next_check}*", ":hourglass_flowing_sand:"
            )
            log(f"No slots. Waiting {POLL_INTERVAL}s ...")
            time.sleep(POLL_INTERVAL)

        else:
            slack(
                f"*No slot found after {MAX_WAIT_HOURS} hours.*\n"
                f"Type `/book` tomorrow morning to try again.", ":x:"
            )
            log("Timed out.")

        browser.close()
        log("Done. Browser closed.")


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
