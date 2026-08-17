from enum import Enum

from coding_agent_bench.builder import SupportedAgent


ALLOWED_AGENTS: set[str] = {a.value for a in SupportedAgent}

ALLOWED_DATASETS: set[str] = {
    "swe-bench-verified",
    "swe-bench-lite",
    "swe-bench",
}

DEFAULT_N_CONCURRENT = 1
DEFAULT_MODEL_MAX_LEN = 262000


class Column(int, Enum):
    TIMESTAMP = 0
    AGENT = 1
    DATASET = 2
    MODEL_NAME = 3
    SERVER_URL = 4
    EMAIL = 5
    STATUS = 6
    JOB_ID = 7
    ERROR = 8
    NOTIFIED_QUEUED = 9
    NOTIFIED_DONE = 10


class Status(str, Enum):
    QUEUED = "Queued"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    NEEDS_REVIEW = "Needs Review"


def generate_job_name(agent: str, dataset: str, model_name: str) -> str:
    short_name = model_name.rsplit("/", 1)[-1]
    return f"{agent}_{dataset}_{short_name}"
