import scrapy
from crawler.spiders.base_spider import BaseStartupSpider
from crawler.models import JobItem

CAREER_KEYWORDS = {"careers", "jobs", "hiring", "work-with-us", "join-us", "join us", "we're hiring"}

GITHUB_ORGS = [
    "openai", "anthropic", "mistralai", "huggingface", "langchain-ai",
    "vercel", "supabase", "shadcn-ui", "trpc", "planetscale",
]


class GitHubOrgSpider(BaseStartupSpider):
    """
    Checks GitHub org pages and their pinned repo READMEs for career links.
    Takes a configurable list of org names via GITHUB_ORGS setting.
    Discovered career URLs are fed into the existing ATS detector pipeline.
    """

    name = "github_org"

    def start_requests(self):
        orgs = self.settings.get("GITHUB_ORGS", GITHUB_ORGS)
        if isinstance(orgs, str):
            orgs = [o.strip() for o in orgs.split(",") if o.strip()]
        for org in orgs:
            yield scrapy.Request(
                url=f"https://github.com/orgs/{org}/repositories",
                callback=self.parse_org,
                meta={"org": org, "playwright": True},
                errback=self.handle_error,
            )

    def parse(self, response):
        pass

    def parse_org(self, response):
        org = response.meta["org"]

        # Check org profile bio for career links
        bio_links = response.css("a[href]::attr(href)").getall()
        for link in bio_links:
            if any(kw in link.lower() for kw in CAREER_KEYWORDS):
                yield scrapy.Request(
                    url=response.urljoin(link),
                    callback=self.parse_career_page,
                    meta={"org": org, "playwright": True},
                    errback=self.handle_error,
                )

        # Check pinned/listed repos for career links in README
        pinned_repos = response.css("a[href*='/" + org + "/']::attr(href)").getall()
        seen = set()
        for repo_path in pinned_repos:
            if repo_path in seen:
                continue
            seen.add(repo_path)
            repo_name = repo_path.strip("/").split("/")[-1]
            readme_url = f"https://raw.githubusercontent.com/{org}/{repo_name}/main/README.md"
            yield scrapy.Request(
                url=readme_url,
                callback=self.parse_readme,
                meta={"org": org, "repo": repo_name},
                errback=self.handle_error,
            )

    def parse_readme(self, response):
        org = response.meta["org"]
        repo = response.meta["repo"]
        text = response.text.lower()

        for kw in CAREER_KEYWORDS:
            if kw in text:
                # Extract markdown links containing the keyword
                import re
                pattern = r'\[([^\]]+)\]\((https?://[^\)]+)\)'
                for match in re.finditer(pattern, response.text):
                    label, url = match.group(1), match.group(2)
                    if any(kw in url.lower() or kw in label.lower() for kw in CAREER_KEYWORDS):
                        yield scrapy.Request(
                            url=url,
                            callback=self.parse_career_page,
                            meta={"org": org, "repo": repo, "playwright": True},
                            errback=self.handle_error,
                        )
                break

    def parse_career_page(self, response):
        org = response.meta["org"]

        # Look for job listings on the discovered career page
        for row in response.css("div, li, tr, article"):
            role_text = row.css("h2::text, h3::text, a::text").get("").strip()
            role_url = row.css("a::attr(href)").get("")

            if not role_text or not self.role_matches(role_text):
                continue

            stack_tags = row.css("span::text, li::text").getall()
            if not self.stack_matches(stack_tags):
                continue

            yield JobItem(
                company=org,
                role=role_text,
                source=self.name,
                url=response.urljoin(role_url) if role_url else response.url,
                stack=stack_tags,
                product="",
                location=row.css("span.location::text").get("").strip(),
                posted_at=None,
            )

    def handle_error(self, failure):
        self.logger.warning(
            "[GitHubOrg] Request failed: %s — %s",
            failure.request.url, repr(failure.value),
        )