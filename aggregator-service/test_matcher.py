
from matcher import rank_jobs
import time

fake_jobs = [
    {"id": "1", "company": "OpenAI", "role": "ML Research Engineer", "stack": ["Python", "PyTorch", "CUDA", "Transformers", "RLHF"], "product": "Large language model training infrastructure"},
    {"id": "2", "company": "Zepto", "role": "Data Engineer", "stack": ["Spark", "Airflow", "dbt", "Snowflake", "SQL"], "product": "Real-time inventory and supply chain pipeline"},
    {"id": "3", "company": "Razorpay", "role": "Backend Engineer", "stack": ["Go", "Kafka", "PostgreSQL", "Redis", "gRPC"], "product": "Payment gateway and transaction processing"},
    {"id": "4", "company": "Sarvam AI", "role": "NLP Engineer - Indic Languages", "stack": ["Python", "HuggingFace", "IndicBERT", "FastAPI", "Transformers"], "product": "Hindi and Tamil speech-to-text and translation models"},
    {"id": "5", "company": "CRED", "role": "Frontend Engineer", "stack": ["React", "TypeScript", "GraphQL", "Tailwind"], "product": "Credit card rewards and financial dashboard"},
    {"id": "6", "company": "Anthropic", "role": "Safety Research Intern", "stack": ["Python", "PyTorch", "interpretability", "mechanistic analysis"], "product": "Constitutional AI and alignment research"},
    {"id": "7", "company": "Swiggy", "role": "MLOps Engineer", "stack": ["Docker", "Kubernetes", "MLflow", "Seldon", "Python"], "product": "Model serving and deployment infrastructure"},
    {"id": "8", "company": "Meesho", "role": "Computer Vision Engineer", "stack": ["Python", "OpenCV", "YOLOv8", "TensorFlow", "AWS"], "product": "Product image quality and catalogue tagging"},
]

resume = """
3rd year Computer Science student specializing in Machine Learning and NLP.
Experience building text classification pipelines using HuggingFace Transformers and PyTorch.
Worked on Hindi language models and multilingual NLP tasks including named entity recognition.
Built a YOLOv8-based image classifier for accident severity detection.
Familiar with FastAPI for model deployment and basic Docker containerization.
Contributed to open source ML projects on GitHub.
Strong in Python, comfortable with scikit-learn, NumPy, and pandas.
"""

print("\n========== TEST 1: RANKED OUTPUT ==========")
start = time.time()
results = rank_jobs(fake_jobs, resume)
elapsed = time.time() - start

for i, job in enumerate(results, 1):
    tier = job.get('match_tier', 'N/A')
    score = job.get('match_score', 'N/A')
    print(f"#{i:2}  {tier.upper():8} | score: {score} | {job['role']} at {job['company']}")

scores = [j['match_score'] for j in results]
print(f"\nRanking time : {elapsed:.2f}s")
print(f"Score range  : {min(scores)} — {max(scores)}")
print(f"Avg score    : {round(sum(scores)/len(scores), 4)}")
gap = round(results[0]['match_score'] - results[1]['match_score'], 4)
print(f"#1 vs #2 gap : {gap} {'(clear winner)' if gap > 0.05 else '(close race)'}")

print("\n========== TEST 2: CACHE CHECK ==========")
start2 = time.time()
rank_jobs(fake_jobs, resume)
elapsed2 = time.time() - start2
print(f"First run  : {elapsed:.2f}s")
print(f"Second run : {elapsed2:.2f}s")
print(f"Cache      : {'YES ✅' if elapsed2 < elapsed else 'CHECK MANUALLY'}")

print("\n========== TEST 3: NO RESUME CHECK ==========")
results_empty = rank_jobs(fake_jobs, None)
has_scores = any('match_score' in j for j in results_empty)
print(f"Scores present without resume : {has_scores} (should be False)")
print(f"No crash                      : ✅")

print("\n========== TEST 4: ACCURACY CHECK ==========")
top3 = [r['role'] for r in results[:3]]
expected_top = {"ML Research Engineer", "NLP Engineer - Indic Languages", "Computer Vision Engineer"}
got_top = set(top3)
print(f"Expected top 3 : {expected_top}")
print(f"Got top 3      : {got_top}")
print(f"Top 3 check    : {'PASS ✅' if expected_top == got_top else 'FAIL ❌'}")

bottom2 = [r['role'] for r in results[-2:]]
expected_bottom = {"Frontend Engineer", "Backend Engineer"}
got_bottom = set(bottom2)
print(f"\nExpected bottom 2 : {expected_bottom}")
print(f"Got bottom 2      : {got_bottom}")
print(f"Bottom check      : {'PASS ✅' if expected_bottom == got_bottom else 'FAIL ❌'}")