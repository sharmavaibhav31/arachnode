import logging
import scrapy
from crawler.spiders.base_spider import BaseStartupSpider
from crawler.models import JobItem


class GlassdoorSpider(BaseStartupSpider):
    name = "glassdoor"

    def start_requests(self):
        # Use first target role for URL, or fallback
        role = self._target_roles[0] if self._target_roles else "software engineer"
        slug = role.lower().replace(" ", "-")
        url = f"https://www.glassdoor.com/Job/{slug}-jobs-SRCH_KO0,{len(slug)}.htm"
        yield scrapy.Request(
            url,
            callback=self.parse,
            errback=self.handle_error,
        )

    def parse(self, response):
        for card in response.css("li.react-job-listing, .JobsList_jobListItem__w8s6Z, [data-test='jobListing']"):
            title = (
                card.css("a.jobLink::text").get() or
                card.css(".JobDetails_jobTitle__Rw_As::text").get() or
                card.css("[data-test='job-title']::text").get() or
                ""
            ).strip()
            company = (
                card.css("div.jobInfoItem::text").get() or
                card.css(".EmployerProfile_employerName__8w09x::text").get() or
                card.css("[data-test='employer-name']::text").get() or
                ""
            ).strip()
            job_url = (
                card.css("a.jobLink::attr(href)").get() or
                card.css("a.JobCard_jobTitle___79_a::attr(href)").get() or
                card.css("a[data-test='job-title-link']::attr(href)").get() or
                ""
            )
            location = (
                card.css("span.loc::text").get() or
                card.css("[data-test='location']::text").get() or
                ""
            ).strip()

            if not title or not self.role_matches(title):
                continue

            full_url = response.urljoin(job_url) if job_url else response.url
            if job_url and not full_url.startswith("http"):
                full_url = f"https://www.glassdoor.com{job_url}"

            yield JobItem(
                company=company or "Unknown Company",
                role=title,
                source=self.name,
                url=full_url,
                stack=[],
                product="",
                location=location,
                posted_at=None,
            )

    def handle_error(self, failure):
        self.logger.error(f"Glassdoor request failed: {failure}")