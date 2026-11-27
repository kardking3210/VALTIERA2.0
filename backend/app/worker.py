"""Single-process polling worker for durable research calculation jobs."""
import logging, os, time
from datetime import datetime, timezone
from sqlalchemy import select
from .db import Base, SessionLocal, initialize_storage
from .engines.core import calculate
from .models import EngineRun, ResearchJob, ServiceHeartbeat

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
logger=logging.getLogger("valtiera.worker")

def pulse(db):
    row=db.get(ServiceHeartbeat,"research-worker")
    if row: row.checked_at=datetime.now(timezone.utc)
    else: db.add(ServiceHeartbeat(service="research-worker",checked_at=datetime.now(timezone.utc)))
    db.commit()

def process_one(db):
    job=db.execute(select(ResearchJob).where(ResearchJob.status=="PENDING").order_by(ResearchJob.created_at).with_for_update(skip_locked=True)).scalars().first()
    if not job: return False
    job.status="RUNNING"; job.updated_at=datetime.now(timezone.utc); db.commit()
    try:
        result=calculate(job.engine,job.data,job.parameters)
        execution=EngineRun(user_id=job.user_id,engine=job.engine,model_version=result["model_version"],result=result)
        db.add(execution); db.flush(); job.result={**result,"execution_id":execution.id}; job.status="COMPLETED"; job.error=None
    except Exception as exc:
        logger.exception("Research job %s failed",job.id)
        job.status="FAILED"; job.error=str(exc)[:500]
    job.updated_at=datetime.now(timezone.utc); db.commit(); return True

def run_forever():
    initialize_storage(Base)
    logger.info("VALTIERA research worker starting")
    while True:
        try:
            with SessionLocal() as db:
                pulse(db)
                worked=process_one(db)
            if not worked: time.sleep(float(os.getenv("WORKER_POLL_SECONDS","2")))
        except Exception:
            logger.exception("Worker cycle failed")
            time.sleep(5)

if __name__=="__main__": run_forever()
