"""
OpenClaw Check Module

Responsible for performing OpenClaw health checks and returning structured status information
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import file_read_backwards

from ..core.config import get_config

logger = logging.getLogger(__name__)


class HealthStatus:
    """Health status result"""

    def __init__(
        self,
        status: str,
        message: str,
        details: Optional[Dict] = None,
    ):
        """
        Initialize health status

        Args:
            status: Status level ("healthy", "warning", "error")
            message: Human-readable status message
            details: Additional check-specific parameters
        """
        self.status = status
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict:
        """Convert to dictionary format"""
        return {
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


class OpenClawChecker:
    """OpenClaw health checker"""

    def __init__(self):
        """
        Initialize OpenClaw checker
        """
        config = get_config()
        
        # Get paths from config
        self.openclaw_config_path = Path(config.get_openclaw_config_path())
        self.runtime_log_path = Path(config.get_openclaw_runtime_log_path())
        self.gateway_log_path = Path(config.get_openclaw_gateway_log_path())
        self.agents_dir = Path(config.get_openclaw_agents_dir())
        
        # Load runtime log rules from file
        self.runtime_log_rules = self._load_runtime_log_rules()
        
        # Get maximum window minutes from rules
        self._max_window_minutes = max(
            (rule.get("window_minutes", 1) for rule in self.runtime_log_rules),
            default=10
        )
        
        # Try to get runtime log path from OpenClaw config if it exists
        self._update_runtime_log_path_from_config()

    def _load_runtime_log_rules(self) -> List[Dict]:
        """
        Load runtime log rules from data file

        Returns:
            List[Dict]: List of check rules
        """
        try:
            # Get path to rules file
            rules_file = Path(__file__).parent.parent / "data" / "openclaw_runtime_log_rules.json"
            with open(rules_file, "r", encoding="utf-8") as f:
                rules = json.load(f)
                logger.info(f"Loaded {len(rules)} OpenClaw runtime log rules")
                return rules
        except Exception as e:
            logger.error(f"Failed to load runtime log rules: {e}", exc_info=True)
            # Return empty list if rules file cannot be loaded
            return []

    def _update_runtime_log_path_from_config(self):
        """
        Update runtime log path from OpenClaw config file if it exists
        """
        try:
            if self.openclaw_config_path.exists():
                with open(self.openclaw_config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    logging_config = config.get("logging", {})
                    log_file = logging_config.get("file")
                    if log_file:
                        self.runtime_log_path = Path(log_file)
                        logger.debug(f"Updated runtime log path from OpenClaw config: {self.runtime_log_path}")
        except Exception as e:
            logger.warning(f"Failed to read OpenClaw config for log path: {e}")

    def _parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """
        Parse timestamp from string (ISO format or Unix timestamp)

        Args:
            timestamp_str: Timestamp string

        Returns:
            Optional[datetime]: Parsed datetime or None if failed
        """
        try:
            # Try ISO format first
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            try:
                # Try Unix timestamp (milliseconds or seconds)
                ts = float(timestamp_str)
                if ts > 1e12:  # Milliseconds
                    ts = ts / 1000
                return datetime.fromtimestamp(ts)
            except (ValueError, OSError):
                return None

    def _parse_jsonl_line(self, line: str) -> Optional[Dict]:
        """
        Parse a JSONL line

        Args:
            line: JSONL line string

        Returns:
            Optional[Dict]: Parsed JSON object or None if failed
        """
        try:
            return json.loads(line.strip())
        except (json.JSONDecodeError, AttributeError):
            return None

    def _read_lines_for_window(self, file_path: Path, now: datetime) -> List[str]:
        """
        Read lines from file covering the maximum window time using reverse reading
        
        Strategy:
        - Read backwards from end of file
        - Collect lines until we reach a line older than (now - max_window_minutes)
        - Reverse the collected lines to get chronological order
        
        Args:
            file_path: Path to file
            now: Current datetime
            
        Returns:
            List[str]: List of lines covering the time window (in chronological order)
        """
        lines = []
        
        if not file_path.exists():
            return lines

        try:
            # Calculate cutoff time: lines older than this won't be included
            cutoff_time = now - timedelta(minutes=self._max_window_minutes)
            
            # Read backwards from end of file
            # Limit to reasonable number of lines to avoid reading entire file if timestamps are missing
            max_lines = 100000  # Safety limit
            line_count = 0
            
            with file_read_backwards.FileReadBackwards(file_path, encoding="utf-8") as f:
                for line in f:
                    line_count += 1
                    if line_count > max_lines:
                        logger.warning(f"Reached max_lines limit ({max_lines}) when reading {file_path}")
                        break
                    
                    # Parse line to check timestamp
                    log_entry = self._parse_jsonl_line(line)
                    if log_entry:
                        time_str = log_entry.get("time")
                        if time_str:
                            log_time = self._parse_timestamp(time_str)
                            if log_time:
                                # Stop if we've gone past the cutoff time
                                if log_time < cutoff_time:
                                    break
                                # Add line to collection (newest first, no reversal needed)
                                lines.append(line)
                            else:
                                # Timestamp parsing failed, include the line anyway
                                lines.append(line)
                        else:
                            # No timestamp, include the line anyway (might be recent)
                            lines.append(line)
                    else:
                        # Failed to parse JSON, include the line anyway
                        lines.append(line)
            
            # Keep lines in reverse order (newest first) - no reversal needed
                
        except Exception as e:
            logger.error(f"Failed to read lines from {file_path}: {e}", exc_info=True)

        return lines

    def _check_runtime_log(self, now: datetime) -> List[Dict]:
        """
        Check runtime log for issues

        Args:
            now: Current datetime

        Returns:
            List[Dict]: List of detected issues
        """
        issues = []

        if not self.runtime_log_path.exists():
            return issues

        try:
            # Read lines covering the maximum window time
            lines = self._read_lines_for_window(self.runtime_log_path, now)
            
            if not lines:
                return issues

            # Check each rule
            # Lines are in reverse order (newest first), so we iterate from newest to oldest
            for rule in self.runtime_log_rules:
                window_start = now - timedelta(minutes=rule["window_minutes"])
                matches = 0

                # Iterate from newest to oldest (lines are already in reverse order)
                for line in lines:
                    # Parse JSONL line
                    log_entry = self._parse_jsonl_line(line)
                    if not log_entry:
                        continue

                    # Get timestamp
                    time_str = log_entry.get("time")
                    if not time_str:
                        continue

                    log_time = self._parse_timestamp(time_str)
                    if not log_time:
                        continue
                    
                    # If we've gone past the window start, we can break (lines are in reverse order)
                    if log_time < window_start:
                        break

                    # Check if line matches pattern
                    log_text = json.dumps(log_entry, ensure_ascii=False)
                    if re.search(rule["pattern"], log_text, re.IGNORECASE):
                        matches += 1

                # Check threshold
                if matches >= rule["threshold"]:
                    issues.append(
                        {
                            "status": "error",
                            "message": rule["name"],
                            "details": {
                                "rule": rule["name"],
                                "matches": matches,
                                "threshold": rule["threshold"],
                                "window_minutes": rule["window_minutes"],
                            },
                        }
                    )

        except Exception as e:
            logger.error(f"Failed to check runtime log: {e}", exc_info=True)

        return issues

    def _check_gateway_log(self, now: datetime) -> Optional[Dict]:
        """
        Check gateway error log

        Args:
            now: Current datetime

        Returns:
            Optional[Dict]: Issue if detected, None otherwise
        """
        if not self.gateway_log_path.exists():
            return None

        try:
            # Check if file was modified in the last minute
            mtime = datetime.fromtimestamp(self.gateway_log_path.stat().st_mtime)
            if mtime >= now - timedelta(minutes=1):
                return {
                    "status": "error",
                    "message": "Daemon process error",
                    "details": {
                        "log_path": str(self.gateway_log_path),
                        "last_modified": mtime.isoformat(),
                    },
                }
        except Exception as e:
            logger.error(f"Failed to check gateway log: {e}", exc_info=True)

        return None

    def _check_agent_logs(self, now: datetime) -> Optional[Dict]:
        """
        Check agent session logs

        Args:
            now: Current datetime

        Returns:
            Optional[Dict]: Issue if detected, None otherwise
        """
        if not self.agents_dir.exists():
            return None

        try:
            # Find all JSONL files in sessions directories
            session_files = []
            for agent_dir in self.agents_dir.iterdir():
                if not agent_dir.is_dir():
                    continue
                sessions_dir = agent_dir / "sessions"
                if not sessions_dir.exists():
                    continue

                for jsonl_file in sessions_dir.glob("*.jsonl"):
                    # Check if file was modified in the last minute
                    try:
                        mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
                        if mtime >= now - timedelta(minutes=1):
                            session_files.append(jsonl_file)
                    except OSError:
                        continue

            if not session_files:
                return None

            # Check logs from the past 5 minutes
            window_start = now - timedelta(minutes=5)
            total_lines = 0
            error_lines = 0

            for jsonl_file in session_files:
                try:
                    # Read backwards from end of file, check lines from past 5 minutes
                    with file_read_backwards.FileReadBackwards(jsonl_file, encoding="utf-8") as f:
                        for line in f:
                            log_entry = self._parse_jsonl_line(line)
                            if not log_entry:
                                continue

                            # Get timestamp
                            timestamp = log_entry.get("timestamp")
                            if not timestamp:
                                continue

                            log_time = self._parse_timestamp(str(timestamp))
                            if not log_time:
                                continue
                            
                            # If we've gone past the window start, we can break (reading backwards)
                            if log_time < window_start:
                                break

                            total_lines += 1

                            # Check if it's an error line
                            error_message = log_entry.get("errorMessage")
                            is_error = log_entry.get("isError", False)

                            if (error_message and error_message.strip()) or is_error:
                                error_lines += 1

                except Exception as e:
                    logger.warning(f"Failed to read agent log {jsonl_file}: {e}")

            # Check error rate
            if total_lines > 0:
                error_rate = error_lines / total_lines
                if error_rate >= 0.3:
                    return {
                        "status": "error",
                        "message": "Agent failure rate too high",
                        "details": {
                            "error_rate": error_rate,
                            "error_lines": error_lines,
                            "total_lines": total_lines,
                            "checked_files": len(session_files),
                        },
                    }

        except Exception as e:
            logger.error(f"Failed to check agent logs: {e}", exc_info=True)

        return None

    async def check_all(self) -> HealthStatus:
        """
        Perform all OpenClaw checks

        Returns:
            HealthStatus: Overall health status with aggregated details
        """
        try:
            all_details = {}
            overall_status = "healthy"
            messages = []

            # Perform OpenClaw check
            openclaw_status = await self.check_openclaw_status()
            if openclaw_status:
                all_details["openclaw"] = openclaw_status
                if openclaw_status.get("status") != "healthy":
                    overall_status = openclaw_status.get("status", "warning")
                    messages.append(openclaw_status.get("message", ""))

            # Determine overall message
            if overall_status == "healthy":
                message = "All checks passed"
            else:
                message = "; ".join(messages) if messages else "OpenClaw check issues detected"

            return HealthStatus(
                status=overall_status,
                message=message,
                details=all_details,
            )

        except Exception as e:
            logger.error(f"OpenClaw check failed: {e}", exc_info=True)
            return HealthStatus(
                status="error",
                message=f"OpenClaw check exception: {str(e)}",
                details={},
            )

    async def check_openclaw_status(self) -> Optional[Dict]:
        """
        Check OpenClaw status (by reading files)

        Returns:
            Optional[Dict]: OpenClaw status, or None if check cannot be performed
        """
        try:
            now = datetime.now()
            issues = []

            # Check runtime log
            runtime_issues = self._check_runtime_log(now)
            issues.extend(runtime_issues)

            # Check gateway log
            gateway_issue = self._check_gateway_log(now)
            if gateway_issue:
                issues.append(gateway_issue)

            # Check agent logs
            agent_issue = self._check_agent_logs(now)
            if agent_issue:
                issues.append(agent_issue)

            # Determine overall status
            if issues:
                # Get the most severe status
                statuses = [issue.get("status", "warning") for issue in issues]
                if "error" in statuses:
                    overall_status = "error"
                else:
                    overall_status = "warning"

                # Combine messages
                messages = [issue.get("message", "") for issue in issues]
                message = "; ".join(messages)

                return {
                    "status": overall_status,
                    "message": message,
                    "details": {
                        "issues": issues,
                        "runtime_log_path": str(self.runtime_log_path),
                        "gateway_log_path": str(self.gateway_log_path),
                        "agents_dir": str(self.agents_dir),
                    },
                }
            else:
                return {
                    "status": "healthy",
                    "message": "All OpenClaw checks passed",
                    "details": {
                        "runtime_log_path": str(self.runtime_log_path),
                        "gateway_log_path": str(self.gateway_log_path),
                        "agents_dir": str(self.agents_dir),
                    },
                }

        except Exception as e:
            logger.error(f"OpenClaw status check failed: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"OpenClaw status check failed: {str(e)}",
                "details": {},
            }
