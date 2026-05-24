"""
SoundCloud Repost Deleter — removes all reposts via Selenium (manual login).
"""

from __future__ import annotations

import argparse
import os
import time

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

DEFAULT_PROFILE_URL = os.environ.get("SOUNDCLOUD_PROFILE_URL", "https://soundcloud.com/huntingszn")
REPOST_BUTTON_SELECTOR = "button.sc-button-repost.sc-button-selected"
DELETE_BUTTON_SELECTOR = "button.repostOverlay__formButtonDelete"
LIST_CONTAINER_SELECTOR = "div.lazyLoadingList"


def setup_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def scroll_to_load_all(driver: webdriver.Chrome, max_scrolls: int = 50) -> None:
    container = driver.find_element(By.CSS_SELECTOR, LIST_CONTAINER_SELECTOR)
    last_height = driver.execute_script("return arguments[0].scrollHeight", container)
    for _ in range(max_scrolls):
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", container)
        time.sleep(1.5)
        new_height = driver.execute_script("return arguments[0].scrollHeight", container)
        if new_height == last_height:
            break
        last_height = new_height


def remove_reposts(driver: webdriver.Chrome) -> int:
    removed = 0
    while True:
        buttons = driver.find_elements(By.CSS_SELECTOR, REPOST_BUTTON_SELECTOR)
        if not buttons:
            break
        btn = buttons[0]
        try:
            driver.execute_script("arguments[0].click();", btn)
            wait = WebDriverWait(driver, 10)
            delete_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, DELETE_BUTTON_SELECTOR))
            )
            delete_btn.click()
            removed += 1
            time.sleep(1)
        except (TimeoutException, NoSuchElementException, ElementClickInterceptedException) as exc:
            print(f"Stopped: {exc}")
            break
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete all SoundCloud reposts.")
    parser.add_argument("--profile-url", default=DEFAULT_PROFILE_URL)
    args = parser.parse_args()

    driver = setup_driver()
    try:
        driver.get(args.profile_url)
        input("Log in in the browser, then press Enter to continue...")
        scroll_to_load_all(driver)
        count = remove_reposts(driver)
        print(f"Removed {count} repost(s).")
    finally:
        input("Press Enter to close the browser...")
        driver.quit()


if __name__ == "__main__":
    main()
