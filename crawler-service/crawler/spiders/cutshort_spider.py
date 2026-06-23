import scrapy
import json
from crawler.spiders.base_spider import BaseStartupSpider
from crawler.models import JobItem


class CutshortSpider(BaseStartupSpider):
    name = "cutshort"

    def start_requests(self):
        role_slug = self.settings.get("JOBSEEKER_ROLE", "python").lower().replace(" ", "-")
        url = f"https://cutshort.io/jobs/{role_slug}-jobs"
        yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        # Extract job titles from JSON-LD ItemList (most stable source — changes rarely).
        # Items have no URL field, so JSON-LD titles are matched to cards using their position in the list.
        jsonld_titles = {}
        for raw in response.css('script[type="application/ld+json"]::text').getall():
            try:
                data = json.loads(raw)
                if data.get("@type") == "ItemList":
                    for item in data.get("itemListElement", []):
                        pos = item.get("position")
                        name = item.get("name", "").strip()
                        if pos and name:
                            jsonld_titles[pos] = name
            except (json.JSONDecodeError, AttributeError):
                pass

        # No stable attributes (data-testid, aria-label, etc.) were found on job cards.
        # Using a partial class match as the most reliable option available.
        cards = response.css("div[class*='jEsvIv']")

        if not cards:
            self.logger.warning("No job cards found — jEsvIv selector may need updating")
            return

        for idx, card in enumerate(cards, start=1):
            # URL: href pattern is stable, extracted from the job link.
            # urljoin is used for consistency with other spiders.
            role_url = card.css("a[href*='/job/']::attr(href)").get("")

            # Role: Use JSON-LD as the primary source for job titles.
            # Fall back to page HTML if JSON-LD is unavailable.
            role_text = jsonld_titles.get(idx, "").strip()
            if not role_text:
                role_text = card.css("h2 a::text").get("").strip()

            # Company: usually available in the image alt text.
            # Fallback to h3 text if no logo/company image is present.
            company = card.css("img::attr(alt)").get("").strip()
            if not company:
                company = card.css("h3::text").get("").strip()

            # Location: No stable selector was found for location..
            # Using a class-based selector as the best available option.
            # Update if Cutshort redesigns job card UI.
            location = card.css("div[class*='loAaLs']::text").get("").strip()

            # Stack: Extract listed skills/technologies from the job card.
            # Using a class-based selector because no stable attribute was available.
            # Update if Cutshort redesigns job card UI.
            stack_tags = card.css("div[class*='lfkCpY'] span::text").getall()
            stack_tags = [t.strip() for t in stack_tags if t.strip()]

            if not role_text:
                continue
            if not self.role_matches(role_text):
                continue
            if stack_tags and not self.stack_matches(stack_tags):
                continue

            yield JobItem(
                company=company,
                role=role_text,
                source=self.name,
                url=response.urljoin(role_url),
                stack=stack_tags,
                product="",
                location=location,
                posted_at=None,
            )