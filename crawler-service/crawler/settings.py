import os

BOT_NAME = "Arachnode"
SPIDER_MODULES = ["crawler.spiders"]
NEWSPIDER_MODULE = "crawler.spiders"

# --------------------------------------------------------------------------
# Politeness settings — do not remove these
# --------------------------------------------------------------------------
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 2
RANDOMIZE_DOWNLOAD_DELAY = True          # actual delay: 1s–3s
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 1
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

# --------------------------------------------------------------------------
# Middleware
# --------------------------------------------------------------------------
DOWNLOADER_MIDDLEWARES = {
    "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": None,
    "crawler.middlewares.RotateUserAgentMiddleware": 400,
    "crawler.middlewares.ExponentialBackoffRetryMiddleware": 550,
    "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler": 585,
}

# --------------------------------------------------------------------------
# Retry settings
# --------------------------------------------------------------------------
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]
FAILED_URLS_KEY = "arachnode:failed_urls"
DOWNLOAD_HANDLERS = {
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "http":  "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}

PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True,
    "args": ["--no-sandbox", "--disable-dev-shm-usage"],
}
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30_000   # 30 seconds

# --------------------------------------------------------------------------
# Item pipelines — order matters, lower number runs first
# --------------------------------------------------------------------------
ITEM_PIPELINES = {
    "crawler.pipelines.dedup_pipeline.DeduplicationPipeline":  100,
    "crawler.pipelines.filter_pipeline.StackFilterPipeline":   200,
    "crawler.pipelines.emit_pipeline.RedisStreamPipeline":     300,
}

# --------------------------------------------------------------------------
# Redis connection
# --------------------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# --------------------------------------------------------------------------
# Your profile — override via env vars or -s flags
# --------------------------------------------------------------------------
JOBSEEKER_ROLE = os.getenv("JOBSEEKER_ROLE", "Backend Engineer")
JOBSEEKER_STACK = os.getenv("JOBSEEKER_STACK", "Java,Python,,RESTAPI,FastAPI,PostgreSQL,Kubernetes,Docker")

# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"
