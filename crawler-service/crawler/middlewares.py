import random
import logging
import time
import redis
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
]


class RotateUserAgentMiddleware:
    def process_request(self, request, spider):
        request.headers["User-Agent"] = random.choice(USER_AGENTS)


class ExponentialBackoffRetryMiddleware(RetryMiddleware):
    """
    Replaces Scrapy's default RetryMiddleware with exponential backoff retry logic.

    How it integrates with the crawler pipeline:
    - Registered at priority 550 in DOWNLOADER_MIDDLEWARES, after RotateUserAgentMiddleware (400)
      but before ScrapyPlaywrightDownloadHandler (585)
    - Scrapy's built-in RetryMiddleware is disabled (set to None) to avoid conflicts
    - On failure, returns a new request copy with retry_times incremented
    - Backoff is implemented by setting DOWNLOAD_DELAY on the per-domain slot via
      crawler.engine, keeping retry behavior non-blocking and Twisted-compatible
    - POST/PUT/DELETE requests are never retried (non-idempotent safety)
    - Redis logging failures are silently caught so crawler flow is never interrupted

    Settings:
    - RETRY_TIMES: max retry attempts (default: 3)
    - RETRY_HTTP_CODES: HTTP codes that trigger retry
    - RETRY_BACKOFF_BASE: base for exponential backoff in seconds (default: 2.0)
    - RETRY_BACKOFF_MAX: max backoff cap in seconds (default: 60.0)
    - FAILED_URLS_KEY: Redis key for logging exhausted URLs
    """

    def __init__(self, settings):
        super().__init__(settings)
        self.failed_urls_key = settings.get("FAILED_URLS_KEY", "arachnode:failed_urls")
        self.backoff_base = settings.getfloat("RETRY_BACKOFF_BASE", 2.0)
        self.backoff_max = settings.getfloat("RETRY_BACKOFF_MAX", 60.0)
        try:
            self.redis_client = redis.Redis(
                host=settings.get("REDIS_HOST", "localhost"),
                port=settings.getint("REDIS_PORT", 6379),
                decode_responses=True,
                socket_connect_timeout=2,
            )
        except Exception as exc:
            logger.warning("[Retry] Could not connect to Redis: %s. Failed URLs will not be logged.", exc)
            self.redis_client = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    def process_response(self, request, response, spider):
        if request.meta.get("dont_retry", False):
            return response
        if request.method.upper() in ("POST", "PUT", "DELETE"):
            return response
        if response.status in self.retry_http_codes:
            retry_count = request.meta.get("retry_times", 0)
            reason = response_status_message(response.status)
            return self._retry_or_drop(request, reason, retry_count, spider) or response
        return response

    def process_exception(self, request, exception, spider):
        if request.method.upper() in ("POST", "PUT", "DELETE"):
            return None
        if isinstance(exception, self.EXCEPTIONS_TO_RETRY) and not request.meta.get("dont_retry", False):
            retry_count = request.meta.get("retry_times", 0)
            return self._retry_or_drop(request, exception, retry_count, spider)

    def _retry_or_drop(self, request, reason, retry_count, spider):
        if retry_count < self.max_retry_times:
            backoff = min(self.backoff_base ** retry_count, self.backoff_max)
            logger.warning(
                "[Retry] %s | attempt %d/%d | reason: %s | backoff: %.1fs",
                request.url, retry_count + 1, self.max_retry_times, reason, backoff,
            )
            # Apply backoff via per-domain slot delay — Twisted-compatible, non-blocking
            try:
                slot = spider.crawler.engine.downloader.slots.get(request.meta.get("download_slot"))
                if slot:
                    slot.delay = backoff
            except Exception:
                pass  # silently skip if slot not accessible
            retryreq = request.copy()
            retryreq.meta["retry_times"] = retry_count + 1
            retryreq.dont_filter = True
            return retryreq
        else:
            logger.error(
                "[Retry] Exhausted %d retries for %s | reason: %s | logging to Redis.",
                self.max_retry_times, request.url, reason,
            )
            self._log_to_redis(request.url, reason)
            return None

    def _log_to_redis(self, url, reason):
        if self.redis_client is None:
            return
        try:
            entry = f"{url} | {reason} | {time.strftime('%Y-%m-%dT%H:%M:%S')}"
            self.redis_client.lpush(self.failed_urls_key, entry)
            logger.info("[Retry] Logged failed URL to Redis key '%s'.", self.failed_urls_key)
        except Exception as exc:
            logger.warning("[Retry] Could not log to Redis: %s", exc)