# api.py — reactor must be installed before ANY other twisted import
import scrapy.utils.reactor
scrapy.utils.reactor.install_reactor(
    'twisted.internet.asyncioreactor.AsyncioSelectorReactor'
)

# NOW safe to import twisted and scrapy components
import os
import logging
import threading
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from twisted.internet import reactor, defer
from scrapy.crawler import CrawlerRunner
from scrapy.utils.project import get_project_settings

from crawler.spiders.remotive_spider import RemotiveSpider
from crawler.spiders.yc_spider import YCJobsSpider
from crawler.spiders.wellfound_spider import WellfoundSpider
from crawler.spiders.cutshort_spider import CutshortSpider
from crawler.spiders.glassdoor import GlassdoorSpider

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(name)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Crawler API")

class CrawlRequest(BaseModel):
    spider: str
    roles: list[str] = []   # empty = use env var defaults
    stack: list[str] = []   # empty = use env var defaults

runner = None
reactor_thread = None

def start_reactor():
    """Run the Twisted reactor in a background thread."""
    reactor.run(installSignalHandlers=False)

@app.on_event("startup")
def startup_event():
    global runner, reactor_thread
    os.environ.setdefault('SCRAPY_SETTINGS_MODULE', 'crawler.settings')
    settings = get_project_settings()
    runner = CrawlerRunner(settings)
    
    # Start Twisted reactor in background thread
    reactor_thread = threading.Thread(target=start_reactor, daemon=True)
    reactor_thread.start()
    logger.info("Twisted reactor started in background thread")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "An internal error occurred",
            "path": str(request.url.path),
            "hint": "Check service logs for details"
        }
    )

def _run_spider(spider_name: str, roles: list[str], stack: list[str]):
    spiders = {
        "remotive": RemotiveSpider,
        "yc_jobs": YCJobsSpider,
        "wellfound": WellfoundSpider,
        "cutshort": CutshortSpider,
        "glassdoor": GlassdoorSpider,
    }
    spider_cls = spiders.get(spider_name)
    if not spider_cls:
        logger.error(f"Spider not found: {spider_name}")
        return
    
    settings_override = {}
    if roles:
        settings_override["JOBSEEKER_ROLES"] = roles
        settings_override["JOBSEEKER_ROLE"] = roles[0]  # compat
    if stack:
        settings_override["JOBSEEKER_STACK"] = ",".join(stack)
    
    logger.info(f"Scheduling spider: {spider_name} roles={roles} stack={stack}")
    
    from scrapy.utils.project import get_project_settings
    settings = get_project_settings()
    settings.update(settings_override)
    
    reactor.callFromThread(
        runner.crawl,
        spider_cls,
        custom_settings=settings_override,
        roles=roles,
        stack=stack,
    )

@app.post("/crawl")
async def trigger_crawl(req: CrawlRequest, background_tasks: BackgroundTasks):
    valid = {"remotive", "yc_jobs", "wellfound", "cutshort", "glassdoor"}
    if req.spider not in valid:
        return JSONResponse(
            status_code=400,
            content={"error": f"Unknown spider: {req.spider}. Valid: {sorted(valid)}"}
        )
    background_tasks.add_task(_run_spider, req.spider, req.roles, req.stack)
    return {"triggered": True, "spider": req.spider, "status": "scheduled"}

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "reactor_running": reactor.running if reactor else False
    }
