import scrapy
from abc import abstractmethod


class BaseStartupSpider(scrapy.Spider):
    """
    All crawlers inherit from here.
    Stack matching and profile config are centralised so each
    spider only needs to worry about parsing its own source.
    """

    custom_settings = {
        "DOWNLOAD_DELAY": 2,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._target_stack: set[str] = set()
        self._target_roles: list[str] = []
        if "roles" in kwargs and kwargs["roles"]:
            r = kwargs["roles"]
            if isinstance(r, str):
                self._target_roles = [x.strip().lower() for x in r.split(",") if x.strip()]
            else:
                self._target_roles = [x.strip().lower() for x in r if x.strip()]
        if "stack" in kwargs and kwargs["stack"]:
            s = kwargs["stack"]
            if isinstance(s, str):
                self._target_stack = {x.strip().lower() for x in s.split(",") if x.strip()}
            else:
                self._target_stack = {x.strip().lower() for x in s if x.strip()}

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        
        # Support JOBSEEKER_ROLES (list) or JOBSEEKER_ROLE (string)
        if not spider._target_roles:
            roles_list = crawler.settings.getlist("JOBSEEKER_ROLES", [])
            if not roles_list:
                raw = crawler.settings.get("JOBSEEKER_ROLE", "")
                roles_list = [r.strip() for r in raw.split(",") if r.strip()]
            spider._target_roles = [r.lower() for r in roles_list]
        
        if not spider._target_stack:
            raw_stack = crawler.settings.get("JOBSEEKER_STACK", "")
            spider._target_stack = {
                s.strip().lower() for s in raw_stack.split(",") if s.strip()
            }
        return spider

    def role_matches(self, role_text: str) -> bool:
        """
        Returns True if the job title contains any of the target
        role phrases as a whole phrase (not word-by-word).
        
        Example: target_roles = ["backend engineer", "sde intern"]
          "Backend Engineer - Python" → True  (contains "backend engineer")
          "Frontend Engineer" → False
          "Civil Engineer" → False
          "SDE Intern - Bangalore" → True  (contains "sde intern")
        """
        if not self._target_roles:
            return True
        text = role_text.lower()
        return any(phrase in text for phrase in self._target_roles)

    def stack_matches(self, tags: list[str]) -> bool:
        if not self._target_stack:
            return True
        normalised = {t.strip().lower() for t in tags}
        return bool(self._target_stack.intersection(normalised))

    @abstractmethod
    def parse(self, response): ...
