class LeverParser:
    """
    Lever exposes a clean JSON API at:
    https://api.lever.co/v0/postings/{company}?mode=json
    No scraping needed — just a GET request.
    """
    def parse(self, company_slug: str) -> list[dict]:
        import httpx
        resp = httpx.get(f"https://api.lever.co/v0/postings/{company_slug}?mode=json")
        return [
            {
                "role": job["text"],
                "team": job["categories"].get("team"),
                "location": job["categories"].get("location"),
                "url": job["hostedUrl"],
                "posted_at": job["createdAt"],  # Unix ms timestamp
            }
            for job in resp.json()
        ]