import scrapy
from crawler.spiders.base_spider import BaseStartupSpider
from crawler.models import JobItem


class YCJobsSpider(BaseStartupSpider):
    """
    Crawls news.ycombinator.com/jobs (the monthly 'Ask HN: Who is hiring?' threads)
    and ycombinator.com/jobs directly.

    This is plain HTML — no JS rendering needed, fastest spider to run.
    """
    name = "yc_jobs"
    start_urls = ["https://www.ycombinator.com/jobs"]

    def parse(self, response):
        for row in response.css("div.company"):
            company = row.css("h4 a::text").get("").strip()
            roles = row.css("div.job a")

            for role_el in roles:
                role_text = role_el.css("::text").get("").strip()
                role_url = role_el.attrib.get("href", "")

                if not self.role_matches(role_text):
                    continue

                # Stack tags live in the company card, not the role row
                stack_tags = row.css("span.tag::text").getall()

                if not self.stack_matches(stack_tags):
                    continue

                yield JobItem(
                    company=company,
                    role=role_text,
                    source=self.name,
                    url=response.urljoin(role_url),
                    stack=stack_tags,
                    product=row.css("p.description::text").get("").strip(),
                    location=row.css("span.location::text").get("").strip(),
                    posted_at=None,
                )

        # Pagination
        next_page = response.css("a.next::attr(href)").get()
        if next_page:
            yield response.follow(next_page, self.parse)
