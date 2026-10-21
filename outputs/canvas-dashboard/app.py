#!/usr/bin/env python3
"""A localhost-only, read-only Canvas assignment dashboard."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP_DIR = Path(__file__).resolve().parent
PORT = 8765
SKILL_DIR = Path.home() / ".codex" / "skills" / "canvas-study-assistant"
sys.dont_write_bytecode = True
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

try:
    from canvas_study import runtime
except Exception as exc:  # pragma: no cover - surfaced in the browser as a setup hint
    runtime = None
    IMPORT_ERROR = type(exc).__name__
else:
    IMPORT_ERROR = None

DATA_DIR = Path.home() / "AppData" / "Local" / "CanvasStudyDashboard"
if sys.platform != "win32":
    import os
    DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "CanvasStudyDashboard"
TASKS_FILE = DATA_DIR / "study_tasks.json"
TASKS_LOCK = threading.Lock()
SESSION_CONNECTION_LOCK = threading.Lock()
SESSION_CONNECTION: dict | None = None
COMPLETED_STATES = {"submitted", "graded", "pending_review", "complete"}
MANUAL_TYPES = {"none", "on_paper"}
HISTORICAL_DAYS = 180
COURSE_END_GRACE_DAYS = 30


def _local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _safe_iso(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone()
    except ValueError:
        return None


def _status(assignment: dict, now: dt.datetime) -> tuple[str, str]:
    submission = assignment.get("submission") or {}
    workflow = str(submission.get("workflow_state") or "").lower()
    if submission.get("excused"):
        return "completed", "免交"
    if submission.get("submitted_at") or workflow in COMPLETED_STATES:
        return "completed", "已提交"
    kinds = {str(kind).lower() for kind in assignment.get("submission_types", [])}
    if kinds and kinds.issubset(MANUAL_TYPES):
        return "manual", "需线下确认"
    due = _safe_iso(assignment.get("due_at"))
    if not due:
        return "undated", "未设截止日期"
    if due < now - dt.timedelta(days=HISTORICAL_DAYS):
        return "historical", "历史任务"
    if due and due < now:
        return "overdue", "已逾期"
    return "pending", "待完成"


def _assignment_row(course: dict, assignment: dict, now: dt.datetime, canvas_host: str) -> dict:
    status, label = _status(assignment, now)
    due = _safe_iso(assignment.get("due_at"))
    submission = assignment.get("submission") or {}
    candidate_url = assignment.get("html_url")
    parsed_url = urlparse(candidate_url) if isinstance(candidate_url, str) else None
    safe_url = candidate_url if parsed_url and parsed_url.scheme == "https" and parsed_url.netloc == canvas_host else None
    return {
        "id": str(assignment.get("id", "")),
        "course_id": str(course.get("id", "")),
        "course": str(course.get("name") or course.get("course_code") or "未命名课程"),
        "course_code": str(course.get("course_code") or ""),
        "name": str(assignment.get("name") or "未命名任务"),
        "due_at": assignment.get("due_at") if isinstance(assignment.get("due_at"), str) else None,
        "status": status,
        "status_label": label,
        "points": assignment.get("points_possible"),
        "url": safe_url,
        "submitted_at": submission.get("submitted_at"),
    }


def _is_student_course(course: dict) -> bool:
    enrollments = course.get("enrollments") or []
    return any(
        str(enrollment.get("type", "")).lower() == "student"
        or str(enrollment.get("role", "")).lower() == "studentenrollment"
        for enrollment in enrollments
    )


def _course_end_reason(course: dict, rows: list[dict], now: dt.datetime) -> str | None:
    workflow = str(course.get("workflow_state") or "").lower()
    enrollment_states = {
        str(enrollment.get("enrollment_state") or "").lower()
        for enrollment in course.get("enrollments") or []
    }
    if workflow in {"completed", "concluded"} or enrollment_states.intersection({"completed", "concluded"}):
        return "Canvas 已标记课程结束"
    course_end = _safe_iso(course.get("end_at"))
    if course_end and course_end < now:
        future_work = any(
            (due := _safe_iso(row.get("due_at"))) is not None and due > now and row.get("status") != "completed"
            for row in rows
        )
        if future_work:
            return None
        return "Canvas 设置的课程结束日期已过"

    dated_rows = [row for row in rows if row.get("due_at") and _safe_iso(row["due_at"])]
    if len(dated_rows) < 3:
        return None
    last_due = max(_safe_iso(row["due_at"]) for row in dated_rows)
    if last_due > now - dt.timedelta(days=COURSE_END_GRACE_DAYS):
        return None
    if all(row["status"] == "completed" for row in dated_rows):
        return "有截止日期的作业均已完成，最近截止日已超过 30 天"
    return None


def load_canvas_data() -> dict:
    if runtime is None:
        raise RuntimeError(f"Canvas connector could not load ({IMPORT_ERROR or 'setup error'}). Reinstall the Canvas Study Assistant skill.")
    with SESSION_CONNECTION_LOCK:
        session = dict(SESSION_CONNECTION) if SESSION_CONNECTION else None
    if session:
        cfg = session["config"]
        api = runtime.Canvas(cfg["canvas_url"], session["token"])
    else:
        api, cfg = runtime.client()
    # Read Canvas directly instead of using the helper's disk cache. The
    # dashboard promises fresh status on each sync and should not need to
    # write connector cache files just to render the page.
    all_courses = api.pages(
        "/api/v1/courses",
        [("enrollment_state", "active"), ("include[]", "enrollments"), ("per_page", "100")],
    )
    active_courses = [course for course in all_courses if _is_student_course(course)]
    now = _local_now()
    canvas_host = urlparse(cfg.get("canvas_url", "")).netloc

    def get_course_assignments(course: dict) -> tuple[dict, list[dict]]:
        try:
            assignments = api.pages(
                f"/api/v1/courses/{course['id']}/assignments",
                [("include[]", "submission"), ("include[]", "overrides"), ("all_dates", "true"), ("per_page", "100")],
            )
            rows = [_assignment_row(course, item, now, canvas_host) for item in assignments if item.get("published", True)]
            return course, rows
        except Exception as exc:
            # Do not return raw connector errors: they can contain request details.
            return course, [{"error": type(exc).__name__}]

    rows: list[dict] = []
    course_summaries: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(get_course_assignments, active_courses))
    for course, course_rows in results:
        error = next((row.get("error") for row in course_rows if row.get("error")), None)
        clean_rows = [row for row in course_rows if not row.get("error")]
        ended_reason = _course_end_reason(course, clean_rows, now) if not error else None
        rows.extend(clean_rows)
        course_summaries.append({
            "id": str(course.get("id", "")),
            "name": str(course.get("name") or course.get("course_code") or "未命名课程"),
            "course_code": str(course.get("course_code") or ""),
            "assignment_count": len(clean_rows),
            "ended": bool(ended_reason),
            "ended_reason": ended_reason,
            "error": bool(error),
        })
    rows.sort(key=lambda row: (row["due_at"] is None, row["due_at"] or "9999"))
    return {
        "courses": course_summaries,
        "assignments": rows,
        "synced_at": now.isoformat(),
        "timezone": cfg.get("timezone") or now.tzname() or "本地时间",
        "source": "Canvas 实时读取",
        "connection_storage": "memory" if session else "credential_manager",
    }


def read_tasks() -> list[dict]:
    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        return [item for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)] if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def write_tasks(tasks: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = TASKS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(TASKS_FILE)


class Handler(BaseHTTPRequestHandler):
    server_version = "CanvasStudyDashboard/1.0"

    def log_message(self, _format: str, *args) -> None:
        # Canvas course names and task titles should not be written to terminal logs.
        return

    def _headers(self, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "").lower() in {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            self.send_error(403)
            return
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(200, {"ok": True})
        elif path == "/api/tasks":
            with TASKS_LOCK:
                self._send_json(200, {"tasks": read_tasks()})
        elif path == "/api/data":
            try:
                self._send_json(200, load_canvas_data())
            except Exception as exc:
                message = str(exc)
                if "Saved token unavailable" in message:
                    hint = "Canvas 配置存在，但本机凭证管理器中没有可读取的 Token。可以直接在本页打开“Canvas 连接”，输入新 Token 并保存。"
                elif "Canvas is not configured" in message:
                    hint = "本机尚未配置 Canvas。可以直接在本页打开“Canvas 连接”，填写学校 Canvas 地址和 Token 完成初始化。"
                elif "401" in message or "unauthorized" in message.lower():
                    hint = "Canvas Token 已失效或被撤销。可以直接在本页打开“Canvas 连接”，输入新 Token 并保存。"
                elif "Credential Manager" in message:
                    hint = "Windows 凭证管理器读取失败。可以在本页打开“Canvas 连接”重新验证并保存 Token。"
                else:
                    hint = "暂时无法读取 Canvas。请检查网络、Token 有效期和学校 Canvas 服务状态。"
                try:
                    canvas_url = (runtime.config() or {}).get("canvas_url", "") if runtime else ""
                except Exception:
                    canvas_url = ""
                self._send_json(502, {"error": hint, "can_reconnect": any(key in message for key in ("Saved token unavailable", "Canvas is not configured", "401", "unauthorized", "Credential Manager")), "canvas_url": canvas_url})
        else:
            assets = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"), "/styles.css": ("styles.css", "text/css; charset=utf-8"), "/improvements.css": ("improvements.css", "text/css; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8")}
            asset = assets.get(path)
            if not asset:
                self.send_error(404)
                return
            body = (APP_DIR / asset[0]).read_bytes()
            self.send_response(200)
            self._headers(asset[1])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            self.send_error(403)
            return
        path = urlparse(self.path).path
        origin = self.headers.get("Origin", "")
        if origin and origin not in {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}:
            self.send_error(403)
            return
        if path == "/api/shutdown":
            global SESSION_CONNECTION
            with SESSION_CONNECTION_LOCK:
                SESSION_CONNECTION = None
            self._send_json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/api/reconnect":
            allowed_origins = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
            if origin not in allowed_origins or not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                self.send_error(403)
                return
            self._handle_reconnect()
            return
        if path != "/api/tasks":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 4096:
                raise ValueError("bad size")
            payload = json.loads(self.rfile.read(size))
            action = payload.get("action")
            with TASKS_LOCK:
                tasks = read_tasks()
                if action == "add":
                    title = str(payload.get("title", "")).strip()[:160]
                    if not title:
                        raise ValueError("empty title")
                    task = {"id": __import__("uuid").uuid4().hex, "title": title, "done": False, "created_at": _local_now().isoformat()}
                    tasks.append(task)
                elif action == "toggle":
                    task = next((item for item in tasks if item["id"] == str(payload.get("id", ""))), None)
                    if not task:
                        raise ValueError("task not found")
                    task["done"] = not bool(task.get("done"))
                elif action == "delete":
                    tasks = [item for item in tasks if item["id"] != str(payload.get("id", ""))]
                else:
                    raise ValueError("unknown action")
                write_tasks(tasks)
            self._send_json(200, {"tasks": tasks})
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "清单操作无效，请重试。"})

    def _handle_reconnect(self) -> None:
        token = ""
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 8192:
                raise ValueError("bad size")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("bad payload")
            token = str(payload.get("token", "")).strip()
            if not token or len(token) > 4096:
                raise ValueError("bad token")
            if runtime is None:
                self._send_json(503, {"error": "本机 Canvas Study Assistant 未就绪，请先在 Codex 中完成 Canvas 初始化。"})
                return

            raw_url = str(payload.get("canvas_url", "")).strip()
            parsed_input = urlparse(raw_url if "://" in raw_url else f"https://{raw_url}")
            if parsed_input.username or parsed_input.password or parsed_input.scheme != "https":
                self._send_json(400, {"error": "Canvas 地址必须是 HTTPS 学校域名，不能包含用户名或密码。"})
                return
            base = runtime.normalize_url(raw_url)
            profile, student_courses = runtime.validate(base, token)
            user_id = str(profile.get("id", ""))
            if not user_id:
                self._send_json(400, {"error": "Canvas 没有返回账户信息，Token 未保存。"})
                return

            cfg = runtime.config() or {}
            old_user_id = str(cfg.get("canvas_user_id", ""))
            if old_user_id and old_user_id != user_id:
                self._send_json(409, {"error": "这个 Token 属于另一个 Canvas 账户。为避免覆盖现有连接，本次没有保存；请先在 Codex 中确认账户切换。"})
                return

            connection_cfg = dict(cfg)
            connection_cfg.update({
                "canvas_url": base,
                "canvas_user_id": user_id,
                "canvas_user_name": profile.get("name"),
                "timezone": profile.get("time_zone") or "UTC",
                "credential_mode": "system",
                "cache_mode": cfg.get("cache_mode") or "standard",
            })
            if payload.get("session_only") is True:
                global SESSION_CONNECTION
                with SESSION_CONNECTION_LOCK:
                    SESSION_CONNECTION = {"token": token, "config": connection_cfg}
                self._send_json(200, {
                    "connected": True,
                    "storage": "memory",
                    "user_name": profile.get("name") or "Canvas 学生账户",
                    "course_count": len(student_courses),
                })
                return
            try:
                runtime.save_token(token, "system", base, user_id)
            except Exception as exc:
                if "Credential Manager" in str(exc) or "1312" in str(exc):
                    self._send_json(503, {
                        "error": "Windows 凭证管理器暂时不能保存 Token。可勾选“仅本次看板运行使用”，再提交一次；关闭看板服务后需要重新输入。",
                        "credential_unavailable": True,
                    })
                    return
                raise
            cfg.update(connection_cfg)
            runtime.secure_write(runtime.config_path(), cfg)
            shutil.rmtree(runtime.cache_dir(), ignore_errors=True)
            with SESSION_CONNECTION_LOCK:
                SESSION_CONNECTION = None
            self._send_json(200, {
                "connected": True,
                "storage": "credential_manager",
                "user_name": profile.get("name") or "Canvas 学生账户",
                "course_count": len(student_courses),
            })
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "请检查 Canvas 地址和 Token 后重试；Token 未保存。"})
        except Exception as exc:
            # Do not return or log exception details from the credential or API layers.
            if "401" in str(exc) or "unauthorized" in str(exc).lower():
                hint = "Canvas 拒绝了这个 Token。请确认 Token 有效且来自该 Canvas 地址。"
            else:
                hint = "验证或保存失败，Token 未确认可用。请检查地址、网络和 Windows 凭证管理器后重试。"
            self._send_json(502, {"error": hint})
        finally:
            token = ""


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    server = LocalServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
