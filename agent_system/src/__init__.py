"""Healthcare Appointment Rescheduling & Policy Enforcement Agent System.

An end-to-end production-grade Agentic AI System implementing a 12-step execution control loop
with LangGraph, dual-provider model routing (Groq/OpenAI), persistent checkpointing,
deterministic policy guardrails, and async trajectory evals.
"""

__version__ = "1.0.0"

from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Automatically discover and load .env from current directory, parent directory, or root
_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path:
    load_dotenv(_dotenv_path)
else:
    for candidate in [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
    ]:
        if candidate.exists():
            load_dotenv(candidate)
            break

import os
# Automatically enable LangSmith tracing when API key is provided
if os.getenv("LANGCHAIN_API_KEY"):
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
else:
    # Disable tracing when key is empty to avoid 401 warnings
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
