import logging
import scrapy
from scrapy.exceptions import CloseSpider


class GlassdoorJobItem(scrapy.Item):
    company = scrapy.Field()
    role = scrapy.Field()
    url = scrapy.Field()
    description = scrapy.Field()

class GlassdoorSpider(scrapy.Spider):
    name = "glassdoor"
    allowed_domains = ["glassdoor.com", "glassdoor.co.in"]
    
    # Example target page search url for Backend Engineers
    start_urls = ["https://www.glassdoor.com/Job/computer-software-engineer-jobs-SRCH_KO0,26.htm"]
    
    custom_settings = {
        # Configure Playwright as the Scrapy download handler
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "DOWNLOAD_DELAY": 3.0,  # Respectful rate limiting
    }

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url,
                meta={
                    "playwright": True,
                    "playwright_context_kwargs": {
                        "ignore_https_errors": True,
                    }
                },
                callback=self.parse_job_list
            )

    async def parse_job_list(self, response):
        page = response.meta.get("playwright_page")
        
        # 1. Graceful Exit on CAPTCHA / Anti-bot blocks
        if "captcha" in response.url.lower() or response.status in [403, 429]:
            self.logger.error(f"❌ Spider blocked or CAPTCHA triggered at: {response.url}")
            raise CloseSpider(reason="Anti-bot protection triggered. Exiting gracefully.")

        self.logger.info("📡 Successfully reached Glassdoor job index. Initiating explicit elements check...")

        try:
            # 2. Resilient Explicit Waiting instead of hardcoded sleeps
            # Waiting up to 10 seconds for the main job cards list wrapper to load completely
            await page.wait_for_selector(".JobsList_jobsListContainer__9Z9O6", timeout=10000)
        except Exception as e:
            self.logger.warning("⚠️ Primary job card container did not appear in time. Attempting fallback wait...")
            try:
                await page.wait_for_selector("[data-test='jobListing']", timeout=5000)
            except Exception:
                self.logger.error("❌ Failed to resolve layout structural anchors. DOM took too long to settle.")
                return

        # Extract all elements dynamically updated inside the browser session
        content = await page.content()
        selector_response = scrapy.Selector(text=content)
        
        job_cards = selector_response.css(".JobsList_jobListItem__w8s6Z") or selector_response.css("[data-test='jobListing']")
        self.logger.info(f"📊 Extraction Summary: Located {len(job_cards)} active job slots on this cluster view.")

        for card in job_cards:
            item = GlassdoorJobItem()
            
            # 3. Resilient Selector Logic with Fallbacks
            # Extract Company Name
            company_raw = card.css(".EmployerProfile_employerName__8w09x::text").get() or \
                          card.css("[data-test='employer-name']::text").get()
            item['company'] = company_raw.strip() if company_raw else "Unknown Company"
            
            # Extract Role/Job Title
            role_raw = card.css(".JobDetails_jobTitle__Rw_As::text").get() or \
                        card.css("[data-test='job-title']::text").get()
            item['role'] = role_raw.strip() if role_raw else "Not Specified"
            
            # Extract Canonical Clean Link
            relative_url = card.css("a.JobCard_jobTitle___79_a::attr(href)").get() or \
                           card.css("a[data-test='job-title-link']::attr(href)").get()
            item['url'] = response.urljoin(relative_url) if relative_url else response.url
            
            # Description Block Extraction for pipeline AI context text blobs
            desc_raw = card.css(".JobCard_jobDescriptionSnippet__H_g7M::text").get() or \
                       card.css("[data-test='job-description-snippet']::text").get()
            item['description'] = desc_raw.strip() if desc_raw else ""
            
            # 4. Strict Normalized Schema Yielding
            yield item

        # 5. Descriptive Logging around Pagination Transitions
        next_page = selector_response.css("button[data-test='load-more']::attr(href)").get()
        if next_page:
            next_url = response.urljoin(next_page)
            self.logger.info(f"🚀 Moving to page transition -> Targeting: {next_url}")
            yield scrapy.Request(
                next_url,
                meta={"playwright": True},
                callback=self.parse_job_list
            )
        else:
            self.logger.info("🏁 No matching load-more links found. Scraping execution complete.")