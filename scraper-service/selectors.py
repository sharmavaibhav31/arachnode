"""
Selector loader for LinkedIn scraper.
Loads CSS selectors from YAML config file.
"""

import yaml
from pathlib import Path
import logging

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
        """Get a selector by key."""
        selector = self.selectors.get(key)
        if selector is None:
            logger.warning(f"Selector '{key}' not found in config, using fallback")
            return self.fallbacks.get(f"{key}_alt", "")
        return selector
    
    def verify(self) -> dict:
        """Verify all selectors (returns dict with status)."""
        results = {}
        for key, selector in self.selectors.items():
            results[key] = {"selector": selector, "valid": bool(selector)}
        return results
        