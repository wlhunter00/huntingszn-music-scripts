# PRD: soundcloud_unrepost

**Status:** Lost — recreate.

## Purpose

Automate removal of all reposts on a SoundCloud account using Selenium (visible Chrome for manual login).

## Config (hardcoded in original)

```python
PROFILE_URL = "https://soundcloud.com/huntingszn"
USERNAME = "HuntingSzn"
```

Selectors: `button.sc-button-repost.sc-button-selected`, `div.repostOverlay__container`, `button.repostOverlay__formButtonDelete`, `div.lazyLoadingList`.

## Behavior

1. Launch Chrome (webdriver-manager).
2. User logs in manually.
3. Scroll infinite list to load all reposts.
4. Click repost → delete in overlay; loop until done.

## Dependencies

- `selenium`, `webdriver-manager`

## Recreation notes

- **~8 KB** — fragile to SoundCloud DOM changes.
- Move profile URL to `.env`.
- Makefile: `make sc-unrepost` (interactive).
- Do not run headless (login required).
