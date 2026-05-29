import logging
import scrapy
from scrapy.exceptions import CloseSpider
from playwright_stealth import Stealth 

class GlassdoorJobItem(scrapy.Item):
    company = scrapy.Field()
    role = scrapy.Field()
    url = scrapy.Field()
    description = scrapy.Field()

class GlassdoorSpider(scrapy.Spider):
    name = "glassdoor"
    allowed_domains = ["glassdoor.com", "glassdoor.co.in"]
    
    start_urls = ["https://www.glassdoor.com/Job/computer-software-engineer-jobs-SRCH_KO0,26.htm"]
    
    custom_settings = {
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "DOWNLOAD_DELAY": 4.0,
        # Force a genuine user header across standard middleware calls
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        }
    }

    async def init_page(self, page, request):
        """
        Anti-Bot Prevention: Apply evasion scripts cleanly to the browser context page.
        """
        await Stealth().apply_stealth_async(page.context)
        await page.set_extra_http_headers({
            "Accept-Language": "en-US,en;q=0.9"
        })

    async def start(self):
        """
        Updated async start method conforming to modern Scrapy design patterns.
        """
        proxy_server = self.settings.get("PROXY_SERVER")
        
        context_kwargs = {
            "ignore_https_errors": True,
            "viewport": {"width": 1280, "height": 720},
        }
        
        if proxy_server:
            context_kwargs["proxy"] = {"server": proxy_server}

        # NOTE: For local debugging of Cloudflare issues, you can explicitly add 
        # "playwright_launch_options": {"headless": False} inside the meta dict 
        # if you want to inspect what the browser sees visually!

        for url in self.start_urls:
            yield scrapy.Request(
                url,
                meta={
                    "playwright": True,
                    "playwright_page_init_callback": self.init_page,
                    "playwright_context_kwargs": context_kwargs,
                },
                callback=self.parse_job_list
            )

    async def parse_job_list(self, response):
        page = response.meta.get("playwright_page")
        
        # 1. Broaden safety string constraints
        lowered_text = response.text.lower() if response.text else ""
        if "captcha" in response.url.lower() or response.status in [403, 429] or "cloudflare" in lowered_text or "checking your browser" in lowered_text:
            self.logger.error(f"❌ Spider blocked or CAPTCHA triggered at: {response.url}")
            raise CloseSpider(reason="Anti-bot protection triggered. Exiting gracefully.")

        self.logger.info("📡 Successfully reached Glassdoor job index. Initiating explicit elements check...")

        try:
            # Let the browser settle for up to 15 seconds to finish page script calculations
            await page.wait_for_selector(".JobsList_jobsListContainer__9Z9O6", timeout=15000)
        except Exception:
            self.logger.warning("⚠️ Primary job card container did not appear in time. Attempting fallback wait...")
            try:
                await page.wait_for_selector("[data-test='jobListing']", timeout=7000)
            except Exception:
                self.logger.error("❌ Failed to resolve layout structural anchors. DOM took too long to settle.")
                return

        content = await page.content()
        selector_response = scrapy.Selector(text=content)
        
        job_cards = selector_response.css(".JobsList_jobListItem__w8s6Z") or selector_response.css("[data-test='jobListing']")
        self.logger.info(f"📊 Extraction Summary: Located {len(job_cards)} active job slots on this cluster view.")

        for card in job_cards:
            item = GlassdoorJobItem()
            
            company_raw = card.css(".EmployerProfile_employerName__8w09x::text").get() or \
                          card.css("[data-test='employer-name']::text").get()
            item['company'] = company_raw.strip() if company_raw else "Unknown Company"
            
            role_raw = card.css(".JobDetails_jobTitle__Rw_As::text").get() or \
                        card.css("[data-test='job-title']::text").get()
            item['role'] = role_raw.strip() if role_raw else "Not Specified"
            
            relative_url = card.css("a.JobCard_jobTitle___79_a::attr(href)").get() or \
                           card.css("a[data-test='job-title-link']::attr(href)").get()
            item['url'] = response.urljoin(relative_url) if relative_url else response.url
            
            desc_raw = card.css(".JobCard_jobDescriptionSnippet__H_g7M::text").get() or \
                       card.css("[data-test='job-description-snippet']::text").get()
            item['description'] = desc_raw.strip() if desc_raw else ""
            
            yield item

        next_page = selector_response.css("button[data-test='load-more']::attr(href)").get()
        if next_page:
            next_url = response.urljoin(next_page)
            self.logger.info(f"🚀 Moving to page transition -> Targeting: {next_url}")
            
            proxy_server = self.settings.get("PROXY_SERVER")
            context_kwargs = {"ignore_https_errors": True}
            if proxy_server:
                context_kwargs["proxy"] = {"server": proxy_server}

            yield scrapy.Request(
                next_url,
                meta={
                    "playwright": True,
                    "playwright_page_init_callback": self.init_page,
                    "playwright_context_kwargs": context_kwargs
                },
                callback=self.parse_job_list
            )
        else:
            self.logger.info("🏁 No matching load-more links found. Scraping execution complete.")