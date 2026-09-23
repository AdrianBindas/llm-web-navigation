import logging

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .constants import (
    COMPUTED_STYLE_KEYS,
    DEFAULT_USER_AGENT,
    VIEWPORT,
)

logger = logging.getLogger(__name__)



class BrowserSession:
    """
    Context manager around a Playwright Chromium session. Opens a browser and
    context (optionally stealthed), navigates, and exposes screenshot capture
    and DOM snapshot capture.
    """

    def __init__(
        self,
        viewport=None,
        user_agent=DEFAULT_USER_AGENT,
        locale="en-US",
        timezone_id="Europe/Bratislava",
        extra_http_headers=None,
        headless=True,
        stealth=True,
        wait_until="load",
        timeout=60000,
        settle_ms=1500,
        network_idle_ms=3000,
        computed_style_keys=None,
    ):
        self.viewport = viewport or dict(VIEWPORT)
        self.user_agent = user_agent
        self.locale = locale
        self.timezone_id = timezone_id
        self.extra_http_headers = extra_http_headers or {"Accept-Language": "en-US,en;q=0.9"}
        self.headless = headless
        self.stealth = stealth
        self.wait_until = wait_until
        self.timeout = timeout
        # Fixed delay after navigation to let JS render/hydrate (ms).
        self.settle_ms = settle_ms
        # Bounded, best-effort wait for the network to go idle (ms); never fatal.
        self.network_idle_ms = network_idle_ms
        self.computed_style_keys = computed_style_keys or list(COMPUTED_STYLE_KEYS)

        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            user_agent=self.user_agent,
            viewport=self.viewport,
            locale=self.locale,
            timezone_id=self.timezone_id,
            java_script_enabled=True,
            extra_http_headers=self.extra_http_headers,
        )
        self.page = self._context.new_page()
        if self.stealth:
            Stealth().apply_stealth_sync(self.page)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        return False

    def open(self, url):
        """
        Navigate to url. Uses a non-idle wait strategy (default 'load') so pages
        with persistent connections do not hang, then makes a best-effort,
        bounded wait for the network to settle (never fatal), followed by a fixed
        settle delay to let client-side rendering finish.
        """
        self.page.goto(url, wait_until=self.wait_until, timeout=self.timeout)
        if self.network_idle_ms:
            try:
                self.page.wait_for_load_state("networkidle", timeout=self.network_idle_ms)
            except PlaywrightTimeoutError:
                logger.info("Network did not fully idle within %d ms; continuing.",
                            self.network_idle_ms)
        if self.settle_ms:
            self.page.wait_for_timeout(self.settle_ms)

    def screenshot(self, full_page=False):
        return self.page.screenshot(full_page=full_page)

    def capture_snapshot(self):
        client = self.page.context.new_cdp_session(self.page)
        return client.send(
            "DOMSnapshot.captureSnapshot",
            {"computedStyles": self.computed_style_keys},
        )

