from rq import Queue
from redis import Redis
import os

redis_conn = Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
queue = Queue("sigilzero", connection=redis_conn)

def example_job():
    print("Worker is alive.")