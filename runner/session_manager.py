from playwright.sync_api import sync_playwright
import os, json

SESSIONS_DIR = "sessions"


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def login_and_save_session(app_name, login_url):
    ensure_dir(SESSIONS_DIR)
    state_path = os.path.join(SESSIONS_DIR, f"{app_name}.json")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # visible browser
        context = browser.new_context()
        page = context.new_page()
        page.goto(login_url)
        print(f"Log in manually for {app_name}, then press ENTER here when done.")
        input()
        context.storage_state(path=state_path)
        print(f"Session saved to {state_path}")
        browser.close()


def load_session(app_name):
    path = os.path.join(SESSIONS_DIR, f"{app_name}.json")
    if os.path.exists(path):
        return path
    else:
        raise FileNotFoundError(f"No saved session found for {app_name}")
