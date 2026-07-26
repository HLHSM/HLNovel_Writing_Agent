"""Flask routes and application factory."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    session,
    stream_with_context,
)
from werkzeug.exceptions import RequestEntityTooLarge

from .config import BASE_DIR, load_config
from .database import NovelDatabase
from .llm import AgentGateway
from .memory import MemoryManager
from .service import NovelService


def _load_prompts() -> dict[str, str]:
    prompt_dir = BASE_DIR / "prompts"
    return {
        "summary_instruction": (prompt_dir / "summary_instruction.txt").read_text(
            encoding="utf-8"
        ).strip(),
        "writing_instruction": (prompt_dir / "writing_instruction.txt").read_text(
            encoding="utf-8"
        ).strip(),
    }


def _owner_token() -> str:
    token = session.get("owner_token")
    if not token:
        token = str(uuid.uuid4())
        session["owner_token"] = token
        session.permanent = True
    return token


def _word_limit(value: Any, default: int = 1000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if not 100 <= parsed <= 10_000:
        raise ValueError("续写字数必须在 100–10000 之间")
    return parsed


def _writing_mode(value: Any) -> str:
    mode = str(value or "standard")
    if mode not in {"quick", "standard"}:
        raise ValueError("不支持的写作模式")
    return mode


def _decode_upload(file_storage: Any, allowed_extensions: set[str]) -> str:
    filename = file_storage.filename or ""
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in allowed_extensions:
        allowed = "、".join(sorted(allowed_extensions))
        raise ValueError(f"仅支持 {allowed} 文件")
    raw = file_storage.stream.read()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文件编码不支持，请使用 UTF-8 或 GB18030")


def create_app(
    config_overrides: dict[str, Any] | None = None,
    agents: dict[str, Any] | None = None,
) -> Flask:
    config = load_config(overrides=config_overrides)
    app_config = config["app_config"]
    prompts = _load_prompts()

    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.config.update(
        SECRET_KEY=app_config["secret_key"],
        MAX_CONTENT_LENGTH=int(app_config["max_file_size_mb"]) * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 90,
    )
    if config_overrides:
        app.config.update(config_overrides)

    database = NovelDatabase(app_config["database_path"])
    gateway = AgentGateway(config["llm_config"], prompts, agents=agents)
    memory = MemoryManager(gateway, app_config)
    service = NovelService(database, gateway, memory)
    allowed_extensions = {
        extension.lower() for extension in app_config["allowed_extensions"]
    }
    generation_locks: dict[str, threading.Lock] = {}
    locks_guard = threading.Lock()

    app.extensions["novel_database"] = database
    app.extensions["novel_service"] = service
    app.extensions["novel_config"] = config

    def project_or_404(project_id: str) -> dict[str, Any] | None:
        return database.get_project(project_id, _owner_token())

    def project_payload(project: dict[str, Any]) -> dict[str, Any]:
        active = database.active_generations(project["id"])
        history = database.generation_history(project["id"])
        return {
            **{key: value for key, value in project.items() if key != "owner_token"},
            "has_memory": bool(project.get("memory_json")),
            "active_generations": active,
            "generation_history": history,
        }

    def lock_for(project_id: str) -> threading.Lock:
        with locks_guard:
            return generation_locks.setdefault(project_id, threading.Lock())

    def sse_stream(project_id: str, action: str) -> Response:
        project = project_or_404(project_id)
        if not project:
            return Response("project not found", status=404)
        owner = _owner_token()
        project_lock = lock_for(project_id)

        @stream_with_context
        def generate():
            if not project_lock.acquire(blocking=False):
                event = {"type": "error", "content": "该项目已有生成任务正在运行"}
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                return
            try:
                for event in service.generate(project_id, owner, action):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                project_lock.release()

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/")
    def index() -> str:
        _owner_token()
        return render_template(
            "index.html",
            text_length_threshold=app_config["text_length_threshold"],
        )

    @app.get("/health")
    def health() -> Response:
        return jsonify({"status": "ok"})

    @app.post("/process")
    def process_text() -> Response:
        try:
            text_content = str(request.form.get("text_input", "")).strip()
            upload = request.files.get("file")
            if not text_content and upload and upload.filename:
                text_content = _decode_upload(upload, allowed_extensions).strip()
            if not text_content:
                raise ValueError("请输入小说内容或上传文件")

            word_limit = _word_limit(request.form.get("word_limit"))
            mode = _writing_mode(request.form.get("writing_mode"))
            requirements = str(request.form.get("requirements", "")).strip()
            title = str(request.form.get("title", "")).strip()
            if not title:
                first_line = text_content.splitlines()[0].strip()
                title = (first_line[:30] or "未命名小说")

            project = database.create_project(
                owner_token=_owner_token(),
                title=title,
                original_text=text_content,
                requirements=requirements,
                word_limit=word_limit,
                writing_mode=mode,
            )
            return jsonify(
                {
                    "success": True,
                    "session_id": project["id"],
                    "project_id": project["id"],
                    "text_length": len(text_content),
                    "used_summary": len(text_content) > memory.threshold,
                    "word_limit": word_limit,
                }
            )
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400

    @app.get("/stream/<project_id>")
    def stream_writing(project_id: str) -> Response:
        return sse_stream(project_id, "initial")

    def update_settings(project_id: str) -> Response | None:
        project = project_or_404(project_id)
        if not project:
            return Response("project not found", status=404)
        try:
            database.update_project_settings(
                project_id,
                _owner_token(),
                str(request.args.get("requirements", project["requirements"])).strip(),
                _word_limit(request.args.get("word_limit"), project["word_limit"]),
                _writing_mode(request.args.get("writing_mode", project["writing_mode"])),
            )
        except ValueError as exc:
            return Response(str(exc), status=400)
        return None

    @app.get("/continue/<project_id>")
    def continue_writing(project_id: str) -> Response:
        error = update_settings(project_id)
        return error or sse_stream(project_id, "continue")

    @app.get("/restart/<project_id>")
    def restart_writing(project_id: str) -> Response:
        error = update_settings(project_id)
        return error or sse_stream(project_id, "restart")

    @app.get("/api/projects")
    def list_projects() -> Response:
        return jsonify(
            {"success": True, "projects": database.list_projects(_owner_token())}
        )

    @app.get("/api/projects/<project_id>")
    def get_project(project_id: str) -> Response:
        project = project_or_404(project_id)
        if not project:
            return jsonify({"success": False, "error": "项目不存在"}), 404
        return jsonify({"success": True, "project": project_payload(project)})

    @app.post("/api/projects/<project_id>/restore/<generation_id>")
    def restore_version(project_id: str, generation_id: str) -> Response:
        project = project_or_404(project_id)
        if not project:
            return jsonify({"success": False, "error": "项目不存在"}), 404
        restored = database.restore_generation(project_id, generation_id)
        if not restored:
            return jsonify({"success": False, "error": "版本不存在"}), 404
        return jsonify({"success": True, "generation": restored})

    @app.post("/clear/<project_id>")
    @app.delete("/api/projects/<project_id>")
    def clear_project(project_id: str) -> Response:
        deleted = database.delete_project(project_id, _owner_token())
        status = 200 if deleted else 404
        return jsonify({"success": deleted}), status

    @app.errorhandler(RequestEntityTooLarge)
    def file_too_large(_: RequestEntityTooLarge) -> tuple[Response, int]:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"文件不能超过 {app_config['max_file_size_mb']} MB",
                }
            ),
            413,
        )

    return app
