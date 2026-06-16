# matcher.py
# Yeh module completely optional hai — agar resume nahi diya toh
# yeh code kabhi bhi main flow mein nahi aayega

from __future__ import annotations

import hashlib
import logging
import os
import pickle
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# lazy loading 
_model = None

# Resume embeddings cache — disk pe save karenge
# Taaki app restart pe bhi recompute na ho
CACHE_DIR = os.getenv("MATCHER_CACHE_DIR", "/tmp/arachnode_cache")


def _get_model():
    """
    model loads only when called
    """
    global _model
    if _model is None:
        try:
            # sentence-transformers import try karo
            # agar installed nahi hai toh gracefully fail hoga
            from sentence_transformers import SentenceTransformer
            logger.info("Loading SBERT model — MiniLM (lightweight, ~80MB)")
            _model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Model loaded successfully")
        except ImportError:
            # sentence-transformers installed nahi — matching disabled
            logger.warning("sentence-transformers not installed. Matching disabled.")
            return None
    return _model


def _build_jd_text(job: Dict[str, Any]) -> str:
    """
    Job dict se ek clean text string banao jo SBERT encode karega.
    
    models.py se hume pata hai:
    - role      : str
    - company   : str  
    - stack     : List[str]  <-- list hai, string nahi, isliye join karna padega
    - product   : Optional[str]
    
    description field EXISTS NAHI DB mein isliye use nahi kar sakte.
    """
    parts = []
    
    if job.get("role"):
        parts.append(job["role"])
    
    if job.get("company"):
        parts.append(job["company"])
    
    if job.get("stack"):
        parts.append(" ".join(job["stack"]))
    
    if job.get("product"):
        parts.append(job["product"])
    
    
    return " ".join(parts)


def _get_resume_cache_path(resume_text: str) -> str:
    """
    Resume text ka MD5 hash  & cache file  path return .
    Same resume = same hash = same cached embedding, recompution no .
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    resume_hash = hashlib.md5(resume_text.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"resume_{resume_hash}.pkl")


def _get_resume_embedding(model, resume_text: str) -> np.ndarray:
    """
    Resume embedding lo —  cache check , not found then compute .
    """
    cache_path = _get_resume_cache_path(resume_text)
    
    # Cache ?
    if os.path.exists(cache_path):
        logger.info("Resume embedding found in cache — skipping recompute")
        with open(cache_path, "rb") as f:
            return pickle.load(f)
    
    # Not there
    logger.info("Computing resume embedding (first time)...")
    embedding = model.encode(resume_text, convert_to_numpy=True)
    
    with open(cache_path, "wb") as f:
        pickle.dump(embedding, f)
    
    logger.info("Resume embedding cached to disk")
    return embedding


def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """
    Cosine similarity manually — dot product divided by product of magnitudes.
    Score range: 0.0 to 1.0 (same meaning)
    """
    dot = np.dot(vec_a, vec_b)
    norm = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def _score_to_tier(score: float) -> str:
    """
    Numeric score ko human-readable tier mein convert karo.
    Thresholds rough hain — real usage se tune karna padega.
    """
    if score >= 0.55:
        return "strong"
    elif score >= 0.40:
        return "moderate"
    else:
        return "weak"


def rank_jobs(
    jobs: List[Dict[str, Any]],
    resume_text: str,
) -> List[Dict[str, Any]]:
    """
    Main function jo main.py call karega.
    
    Input:  jobs list (DB se aaya, plain dicts) + resume text string
    Output: same jobs list, match_score aur match_tier , sorted by score
    
    
    """
    model = _get_model()
    
    
    if model is None:
        logger.warning("Matcher unavailable — returning jobs unranked")
        return jobs
    
    if not resume_text or not resume_text.strip():
        logger.warning("Empty resume text — returning jobs unranked")
        return jobs
    
    # Resume embedding — cached 
    resume_vec = _get_resume_embedding(model, resume_text)
    
    
    jd_texts = [_build_jd_text(job) for job in jobs]
    jd_vectors = model.encode(jd_texts, convert_to_numpy=True, batch_size=32)
    
    
    scored_jobs = []
    for job, jd_vec in zip(jobs, jd_vectors):
        score = _cosine_similarity(resume_vec, jd_vec)
        scored_jobs.append({
            **job,                          # original job dict
            "match_score": round(score, 4),
            "match_tier": _score_to_tier(score),
        })
    
    #
    scored_jobs.sort(key=lambda j: j["match_score"], reverse=True)
    
    return scored_jobs