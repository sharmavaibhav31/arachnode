import os
import logging
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from twisted.internet import reactor
import scrapy
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

runner = None

@app.on_event("startup")
def startup_event():
    global runner
    os.environ.setdefault('SCRAPY_SETTINGS_MODULE', 'crawler.settings')
    settings = get_project_settings()
    runner = CrawlerRunner(settings)

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

def _run_spider(spider_name: str):
    spiders = {
        "remotive": RemotiveSpider,
        "yc_jobs": YCJobsSpider,
        "wellfound": WellfoundSpider,
        "cutshort": CutshortSpider,
        "glassdoor": GlassdoorSpider
    }
    spider_cls = spiders.get(spider_name)
    if not spider_cls:
        logger.error(f"Spider {spider_name} not found.")
        return
    
    logger.info(f"Running spider: {spider_name}")
    try:
        runner.crawl(spider_cls)
    except Exception as e:
        logger.error(f"Failed to crawl {spider_name}: {e}")

@app.post("/crawl")
async def trigger_crawl(req: CrawlRequest, background_tasks: BackgroundTasks):
    valid_spiders = {"remotive", "yc_jobs", "wellfound", "cutshort", "glassdoor"}
    if req.spider not in valid_spiders:
        return JSONResponse(status_code=400, content={"error": f"Invalid spider: {req.spider}"})
    
    background_tasks.add_task(_run_spider, req.spider)
    return {"triggered": True, "spider": req.spider}

@app.get("/health")
async def health():
    return {"status": "ok"}
