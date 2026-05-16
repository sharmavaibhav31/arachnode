#!/usr/bin/env python3
"""Standalone selector verification tool - tests selectors against LinkedIn."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from selector_loader import SelectorLoader

async def main():
    print("\n" + "="*60)
    print("LinkedIn Selector Verification (Live Test)")
    print("="*60 + "\n")
    
    loader = SelectorLoader()
    
    print("Testing selectors against LinkedIn...\n")
    results = await loader.verify_async("https://www.linkedin.com/jobs")
    
    all_valid = True
    for name, info in results.items():
        status = "✅" if info["valid"] else "❌"
        print(f"{status} {name}: {info['selector']}")
        if not info["valid"]:
            all_valid = False
            if "error" in info:
                print(f"   Error: {info['error']}")
    
    print("\n" + "="*60)
    if all_valid:
        print("✅ All selectors resolved successfully against LinkedIn!")
    else:
        print("❌ Some selectors failed to resolve.")
        print("   Update config/linkedin_selectors.yaml with correct selectors.")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
    