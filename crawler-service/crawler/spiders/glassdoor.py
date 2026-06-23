"""
Glassdoor Job Search Playwright Spider

=========================================
🛠️ PROXY ROTATION CONFIGURATION GUIDE:
=========================================
This spider implements a round-robin `ProxyManager` framework to rotate exit nodes.

1. Via Project Settings (`settings.py`):
   Add a comma-separated string containing your target proxies:
   PROXY_LIST = "http://username:password@proxy1.com:8000, http://username:password@proxy2.com:8000"

2. Via Local Environment Variables:
   Alternatively, you can export it to your runtime context environment:
   export PROXY_LIST="http://proxy1.com:8000,http://proxy2.com:8000"

3. Graceful Direct Fallback:
   If `PROXY_LIST` is left empty or omitted entirely from configuration contexts, 
   the engine will automatically log a message and default to a standard direct network 
   connection without throwing exceptions or causing engine crashes.
"""

import logging
import scrapy
import itertools
from scrapy.exceptions import CloseSpider
from playwright_stealth import Stealth 
from scrapy_playwright.page import PageMethod

class ProxyManager:
    def __init__(self, proxy_list=None):
        """
        Handles a list of proxies and cycles through them.
        If no proxy list is provided, it handles fallback elegantly.
        """
        if proxy_list:
            # Splits a comma-separated string from settings into a clean list
            self.proxies = [p.strip() for p in proxy_list.split(",") if p.strip()]
            self.cycle = itertools.cycle(self.proxies)
        else:
            self.proxies = []
            self.cycle = None

    def get_next_proxy(self):
        if self.cycle:
            return next(self.cycle)
        return None


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
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        }
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.proxy_manager = None

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        """
        Scrapy's native hook to safely grab settings before the spider fully instantiates.
        """
        spider = super(GlassdoorSpider, cls).from_crawler(crawler, *args, **kwargs)
        raw_proxies = crawler.settings.get("PROXY_LIST", "")
        spider.proxy_manager = ProxyManager(raw_proxies)
        return spider

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
        Async start initialization loop applying our custom dynamic proxy logic.
        """
        context_kwargs = {
            "ignore_https_errors": True,
            "viewport": {"width": 1280, "height": 720},
        }
        
        # Query next proxy node from rotation manager
        current_proxy = self.proxy_manager.get_next_proxy() if self.proxy_manager else None
        if current_proxy:
            context_kwargs["proxy"] = {"server": current_proxy}
            self.logger.info(f"🔄 Rotating proxy initialized for start view: {current_proxy}")
        else:
            self.logger.info("ℹ️ No proxies configured. Defaulting to direct connection.")

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
        
        # Broad anti-bot protection fail-safes
        lowered_text = response.text.lower() if response.text else ""
        if "captcha" in response.url.lower() or response.status in [403, 429] or "cloudflare" in lowered_text or "checking your browser" in lowered_text:
            self.logger.error(f"❌ Spider blocked or CAPTCHA triggered at: {response.url}")
            raise CloseSpider(reason="Anti-bot protection triggered. Exiting gracefully.")

        self.logger.info(f"📡 Successfully reached index: {response.url}")

        try:
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
            
            context_kwargs = {"ignore_https_errors": True}
            
            # Rotate to a fresh proxy node for the pagination jump
            next_proxy = self.proxy_manager.get_next_proxy() if self.proxy_manager else None
            if next_proxy:
                context_kwargs["proxy"] = {"server": next_proxy}
                self.logger.info(f"🔄 Rotating proxy mapping updated for next page view: {next_proxy}")
            
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