class ATSDetector:
    PATTERNS = {
        "lever":      lambda url: "jobs.lever.co" in url,
        "greenhouse": lambda url: "boards.greenhouse.io" in url or "grnh.se" in url,
        "ashby":      lambda url: "jobs.ashbyhq.com" in url,
        "workday":    lambda url: "myworkdayjobs.com" in url,
    }

    @classmethod
    def detect(cls, url: str) -> str:
        for ats_name, matcher in cls.PATTERNS.items():
            if matcher(url):
                return ats_name
        return "generic"