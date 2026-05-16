"""
Selector loader for LinkedIn scraper.
Loads CSS selectors from YAML config file.
"""

import yaml
from pathlib import Path
import logging
import asyncio
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class SelectorLoader:
    """Load and manage CSS selectors from YAML config."""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent / "config" / "linkedin_selectors.yaml"

        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        self.selectors = self.config.get("linkedin", {}).get("selectors", {})
        self.fallbacks = self.config.get("linkedin", {}).get("fallbacks", {})

    def get(self, key: str) -> str:
        """Get a selector by key, fallback to alt if available."""
        selector = self.selectors.get(key)
        if selector:
            return selector
        # Try fallback
        fallback_key = f"{key}_alt"
        if fallback_key in self.fallbacks:
            logger.warning(f"Using fallback for '{key}': {self.fallbacks[fallback_key]}")
            return self.fallbacks[fallback_key]
        logger.warning(f"Selector '{key}' not found")
        return ""

    async def verify_async(self, url: str = "https://www.linkedin.com/jobs") -> dict:
        """Actually test selectors against a real LinkedIn page."""
        results = {}
        
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                
                for name, selector in self.selectors.items():
                    try:
                        element = await page.query_selector(selector)
                        results[name] = {
                            "selector": selector,
                            "valid": element is not None,
                            "found": element is not None
                        }
                    except Exception as e:
                        results[name] = {
                            "selector": selector,
                            "valid": False,
                            "error": str(e)
                        }
            finally:
                await browser.close()
        
        return results

    def verify(self) -> dict:
        """Sync wrapper for basic check (no network)."""
        results = {}
        for name, selector in self.selectors.items():
            results[name] = {
                "selector": selector,
                "valid": bool(selector and len(selector) > 0),
                "found": None
            }
        return results
        