---
name: py-observability
description: Observability patterns for Python backends. Use when adding logging, metrics, tracing, or debugging production issues.
---

# Python Observability

## Problem Statement

Production issues are impossible to debug without observability. Logging, metrics, and tracing must be built in from the start. Silent failures, missing context in errors, and lack of metrics make incidents last longer.

---

## Pattern: Structured Logging

**Problem:** Unstructured logs are hard to search and analyze.

```python
# ❌ BAD: Unstructured logging
import logging
logger = logging.getLogger(__name__)

logger.info(f"User {user_id} started assessment {assessment_id}")
logger.error(f"Failed to save answer: {error}")

# ✅ GOOD: Structured logging with structlog
import structlog

logger = structlog.get_logger()

logger.info(
    "assessment_started",
    user_id=str(user_id),
    assessment_id=str(assessment_id),
)

logger.error(
    "answer_save_failed",
    user_id=str(user_id),
    question_id=str(question_id),
    error=str(error),
    error_type=type(error).__name__,
)
```

### structlog Configuration

```python
# app/core/logging.py
import structlog
import logging
import sys

def setup_logging(json_logs: bool = True, log_level: str = "INFO"):
    """Configure structured logging."""
    
    # Shared processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    
    if json_logs:
        # JSON for production (machine-readable)
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Pretty for development (human-readable)
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(),
        ]
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

# Call at startup
setup_logging(json_logs=not settings.DEBUG)
```

---

## Pattern: Request Context Logging

**Problem:** Logs from same request aren't correlated.

```python
import structlog
from contextvars import ContextVar
from uuid import uuid4
from fastapi import Request

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

# Middleware to set request context
@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = str(uuid4())[:8]
    request_id_var.set(request_id)
    
    # Bind to all logs in this request
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        path=request.url.path,
        method=request.method,
    )
    
    try:
        response = await call_next(request)
        return response
    finally:
        structlog.contextvars.unbind_contextvars(
            "request_id", "path", "method"
        )

# Now all logs automatically include request_id
logger.info("processing_assessment")  # Includes request_id, path, method
```

---

## Pattern: Log Levels

```python
logger = structlog.get_logger()

# DEBUG: Detailed diagnostic info (dev only)
logger.debug("query_executed", sql=str(query), params=params)

# INFO: Business events, successful operations
logger.info("assessment_submitted", user_id=user_id, score=score)

# WARNING: Unexpected but handled conditions
logger.warning(
    "rate_limit_approaching",
    user_id=user_id,
    current=current_count,
    limit=rate_limit,
)

# ERROR: Failures that need attention
logger.error(
    "payment_failed",
    user_id=user_id,
    error=str(error),
    payment_id=payment_id,
)

# CRITICAL: System-level failures
logger.critical(
    "database_connection_failed",
    error=str(error),
    host=db_host,
)
```

---

## Pattern: No Silent Early Returns

Same principle as frontend - every early return should log:

```python
# ❌ BAD: Silent early return
async def save_answer(user_id: UUID, question_id: UUID, value: int):
    if not await is_valid_question(question_id):
        return None  # Why did we return? No one knows.

# ✅ GOOD: Observable early return
async def save_answer(user_id: UUID, question_id: UUID, value: int):
    if not await is_valid_question(question_id):
        logger.warning(
            "save_answer_skipped",
            reason="invalid_question",
            user_id=str(user_id),
            question_id=str(question_id),
        )
        return None
```

---

## Pattern: Error Logging with Context

```python
# ❌ BAD: Error without context
try:
    result = await risky_operation()
except Exception as e:
    logger.error(f"Operation failed: {e}")
    raise

# ✅ GOOD: Error with full context
try:
    result = await risky_operation(user_id, assessment_id)
except Exception as e:
    logger.exception(
        "risky_operation_failed",
        user_id=str(user_id),
        assessment_id=str(assessment_id),
        error_type=type(e).__name__,
        error_message=str(e),
    )
    raise
```

---

## Pattern: Prometheus Metrics

```python
# app/core/metrics.py
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from fastapi import Response

# Counters - things that only go up
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

assessment_submissions = Counter(
    "assessment_submissions_total",
    "Total assessment submissions",
    ["skill_area", "status"],  # status: success, validation_error, etc.
)

# Histograms - distribution of values
request_duration = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

db_query_duration = Histogram(
    "db_query_duration_seconds",
    "Database query duration",
    ["query_type"],  # select, insert, update
    buckets=[0.001, 0.01, 0.1, 0.5, 1.0],
)

# Gauges - values that go up and down
active_connections = Gauge(
    "db_active_connections",
    "Active database connections",
)

# Endpoint to expose metrics
@app.get("/metrics")
async def metrics():
    return Response(
        content=generate_latest(),
        media_type="text/plain",
    )
```

### Using Metrics

```python
import time

# Middleware for HTTP metrics
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    
    response = await call_next(request)
    
    duration = time.perf_counter() - start
    request_duration.labels(
        method=request.method,
        path=request.url.path,
    ).observe(duration)
    
    http_requests_total.labels(
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    ).inc()
    
    return response

# In business logic
async def submit_assessment(assessment_id: UUID, session: AsyncSession):
    try:
        result = await _process_submission(assessment_id, session)
        assessment_submissions.labels(
            skill_area=result.skill_area,
            status="success",
        ).inc()
        return result
    except ValidationError:
        assessment_submissions.labels(
            skill_area="unknown",
            status="validation_error",
        ).inc()
        raise
```

---

## Pattern: Error Tracking (Sentry)

Minimal Sentry setup for FastAPI:

```python
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_sdk.init(
    dsn='...',
    environment='production',
    traces_sample_rate=0.1,
    integrations=[FastApiIntegration()],
)
```

For full configuration (PII scrubbing, SQLAlchemy integration), see Sentry's FastAPI docs.

---

## Pattern: Health Checks## Pattern: Health Checks

```python
from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health():
    """Basic liveness check."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@router.get("/health/ready")
async def readiness(session: AsyncSession = Depends(get_session)):
    """Readiness check - verify dependencies."""
    checks = {}
    
    # Database
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
    
    # Redis (if used)
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
    
    all_ok = all(v == "ok" for v in checks.values())
    
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
```

---

## Pattern: Sensitive Data Handling

```python
SENSITIVE_KEYS = {"password", "token", "api_key", "secret", "authorization"}

def redact_sensitive(data: dict) -> dict:
    """Redact sensitive values from dict for logging."""
    result = {}
    for key, value in data.items():
        if any(s in key.lower() for s in SENSITIVE_KEYS):
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = redact_sensitive(value)
        else:
            result[key] = value
    return result

# Use before logging request data
logger.info(
    "request_received",
    body=redact_sensitive(request_body),
)
```

---

## Observability Checklist

When adding new features:

- [ ] Info logs for business events (created, submitted, completed)
- [ ] Warning logs for handled edge cases
- [ ] Error logs with full context for failures
- [ ] No silent early returns
- [ ] Metrics for key operations (counters, histograms)
- [ ] Flow tracing for multi-step operations
- [ ] Sensitive data redacted from logs
- [ ] Request ID in all logs
- [ ] Health check endpoints

When debugging production:

- [ ] Can correlate logs by request_id
- [ ] Can find error in Sentry with context
- [ ] Can see metrics in Prometheus/Grafana
- [ ] Can trace operation through flow_id
