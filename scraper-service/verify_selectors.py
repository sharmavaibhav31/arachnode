#!/usr/bin/env python3
"""Standalone selector verification tool - checks config loading only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from selector_loader import SelectorLoader

def main():
    print("\n" + "="*50)
    print("LinkedIn Selector Verification")
    print("="*50 + "\n")
    
    loader = SelectorLoader()
    
    print("Selectors loaded from config:\n")
    
    all_valid = True
    for name, info in loader.verify().items():
        status = "✅" if info["valid"] else "❌"
        print(f"{status} {name}: {info['selector']}")
        if not info["valid"]:
            all_valid = False
    
    print("\n" + "="*50)
    if all_valid:
        print("✅ All selectors are valid in config file!")
        print("   (Live LinkedIn test blocked by anti-bot measures)")
    else:
        print("❌ Some selectors are empty or missing.")
        print("   Update config/linkedin_selectors.yaml with correct selectors.")
    print("="*50)

if __name__ == "__main__":
    main()
    