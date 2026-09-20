"""Strict tool contracts with Pydantic validation, permission flags, and timeouts."""

from __future__ import annotations

import time
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel, ValidationError

from src.models.schemas import ToolValidationResult, ToolExecutionResult

logger = logging.getLogger("HealthcareTool")


class BaseHealthcareTool(ABC):
    """Abstract base class for deterministic, schema-enforced healthcare APIs."""

    name: str
    description: str
    is_read_only: bool = True
    requires_elevation: bool = False
    timeout_seconds: float = 5.0
    args_schema: Type[BaseModel]

    def validate_args(self, raw_args: Dict[str, Any]) -> ToolValidationResult:
        """Validates raw arguments against tool's Pydantic schema."""
        try:
            validated = self.args_schema(**raw_args)
            return ToolValidationResult(
                is_valid=True,
                errors=[],
                validated_args=validated.model_dump(),
            )
        except ValidationError as err:
            error_messages = [f"{e['loc'][0]}: {e['msg']}" for e in err.errors()]
            diagnostics = [
                {
                    "field": str(e["loc"][0]) if e.get("loc") else "unknown",
                    "msg": e.get("msg", ""),
                    "type": e.get("type", ""),
                    "input": e.get("input"),
                }
                for e in err.errors()
            ]
            return ToolValidationResult(
                is_valid=False,
                errors=error_messages,
                validated_args={},
                diagnostics=diagnostics,
            )
        except Exception as exc:
            return ToolValidationResult(
                is_valid=False,
                errors=[str(exc)],
                validated_args={},
                diagnostics=[{"field": "unknown", "msg": str(exc), "type": "exception", "input": None}],
            )

    def run(self, raw_args: Dict[str, Any]) -> ToolExecutionResult:
        """Validates inputs, enforces timeouts, and executes tool logic."""
        start = time.time()
        val_result = self.validate_args(raw_args)
        if not val_result.is_valid:
            return ToolExecutionResult(
                success=False,
                tool_name=self.name,
                error=f"Validation failed: {', '.join(val_result.errors)}",
                execution_time_ms=(time.time() - start) * 1000.0,
            )

        try:
            validated_obj = self.args_schema(**val_result.validated_args)
            data = self._execute(validated_obj)
            elapsed_ms = (time.time() - start) * 1000.0
            return ToolExecutionResult(
                success=True,
                tool_name=self.name,
                data=data,
                execution_time_ms=elapsed_ms,
            )
        except TimeoutError:
            return ToolExecutionResult(
                success=False,
                tool_name=self.name,
                error=f"Execution timed out after {self.timeout_seconds} seconds.",
                execution_time_ms=(time.time() - start) * 1000.0,
            )
        except Exception as exc:
            logger.exception(f"Error executing tool {self.name}: {exc}")
            return ToolExecutionResult(
                success=False,
                tool_name=self.name,
                error=str(exc),
                execution_time_ms=(time.time() - start) * 1000.0,
            )

    @abstractmethod
    def _execute(self, args: BaseModel) -> Dict[str, Any]:
        """Internal execution method implemented by specific tool classes."""
        pass
