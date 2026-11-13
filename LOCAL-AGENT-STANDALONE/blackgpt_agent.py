#!/usr/bin/env python3
"""Black GPT local workspace agent. Reads/writes only a user-selected project folder."""
from __future__ import annotations
import argparse
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import threading
import tempfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

HOST = "127.0.0.1"
PORT = 8765
TOKEN = secrets.token_urlsafe(24)
WORKSPACE: Path | None = None
MAX_FILE = 1_000_000
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", ".blackgpt-backups", ".idea", ".vscode"}
SENSITIVE_NAME = re.compile(r"^(?:\.env(?:\..*)?|\.npmrc|\.pypirc|.*\.(?:pem|key|p12|pfx)|id_rsa(?:\.pub)?|credentials(?:\.json)?|secrets?(?:\.json)?|service[-_]?account(?:[-_].*)?\.json|firebase-adminsdk.*\.json)$", re.I)
SECRET_CONTENT = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|aws_secret_access_key|password)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{16,}|(?:gsk_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})", re.I)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False,
                                         dir=str(target.parent), prefix=".blackgpt-", suffix=".tmp") as handle:
            temp_name = handle.name
            handle.write(content)
        os.replace(temp_name, target)
    finally:
        if temp_name and os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def choose_folder(initial: Path | None = None) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        chosen = filedialog.askdirectory(title="Выбери папку проекта для Black GPT", initialdir=str(initial or Path.home()), mustexist=True)
        root.destroy()
        return Path(chosen).resolve() if chosen else None
    except Exception as exc:
        print(f"Не удалось открыть диалог выбора папки: {exc}")
        raw = input("Вставь полный путь к папке проекта (пусто — выход): ").strip().strip('"')
        return Path(raw).expanduser().resolve() if raw else None


def is_sensitive(rel: Path) -> bool:
    return any(SENSITIVE_NAME.match(part) for part in rel.parts)


def safe_target(raw: str, allow_missing: bool = False) -> tuple[Path, Path]:
    if WORKSPACE is None:
        raise ValueError("Папка проекта ещё не выбрана.")
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise ValueError("Некорректный путь файла.")
    rel = Path(raw.replace("\\", "/"))
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError("Разрешены только относительные пути внутри выбранной папки.")
    if any(part.lower() in SKIP_DIRS for part in rel.parts) or is_sensitive(rel):
        raise PermissionError("Доступ к системным, служебным или секретным файлам запрещён.")
    root = WORKSPACE.resolve()
    target = (root / rel).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError:
        raise PermissionError("Путь выходит за пределы выбранной папки.")
    # Refuse symlinks anywhere along the route, including a symlink that points back inside.
    cur = root
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            raise PermissionError("Символические ссылки не поддерживаются.")
    if not allow_missing and not target.is_file():
        raise FileNotFoundError("Файл не найден.")
    return rel, target


def tree_data() -> list[dict]:
    if WORKSPACE is None:
        return []
    result: list[dict] = []
    root = WORKSPACE.resolve()
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (base / d).is_symlink())
        for name in sorted(files):
            path = base / name
            try:
                rel = path.relative_to(root)
                if is_sensitive(rel) or path.is_symlink():
                    continue
                size = path.stat().st_size
                if size > MAX_FILE:
                    continue
                # Avoid listing obvious binary files.
                if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".7z", ".exe", ".dll", ".so", ".mp3", ".mp4", ".woff", ".woff2", ".ttf"}:
                    continue
                result.append({"path": rel.as_posix(), "size": size, "extension": path.suffix.lower()})
                if len(result) >= 2500:
                    return result
            except (OSError, ValueError):
                continue
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "BlackGPTAgent/1.0"

    def log_message(self, fmt, *args):
        print("[agent] " + (fmt % args))

    def _cors(self):
        origin = self.headers.get("Origin", "")
        allowed = origin == "https://black-gpt.pages.dev" or bool(re.fullmatch(r"https://[a-z0-9-]+\.black-gpt\.pages\.dev", origin)) or origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:")
        if allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")

    def _send(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self):
        header = self.headers.get("Authorization", "")
        provided = header[7:] if header.startswith("Bearer ") else ""
        return bool(provided) and secrets.compare_digest(provided, TOKEN)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1_200_000:
                raise ValueError("Размер запроса недопустим.")
            data = self.rfile.read(length)
            return json.loads(data.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"Некорректное тело запроса: {exc}")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            return self._send({"ok": True, "service": "Black GPT Local Agent", "authRequired": True})
        if not self._authorized():
            return self._send({"error": "Неверный код подключения. Посмотри код в окне Black GPT Local Agent."}, 401)
        try:
            if parsed.path == "/api/status":
                return self._send({"ok": True, "workspace": str(WORKSPACE) if WORKSPACE else None, "workspaceName": WORKSPACE.name if WORKSPACE else None})
            if parsed.path == "/api/tree":
                return self._send({"workspace": str(WORKSPACE), "files": tree_data()})
            if parsed.path == "/api/read":
                query = parse_qs(parsed.query)
                rel, target = safe_target(unquote(query.get("path", [""])[0]))
                raw = target.read_bytes()
                if len(raw) > MAX_FILE:
                    return self._send({"error": "Файл больше 1 МБ — чтение запрещено."}, 413)
                if b"\x00" in raw:
                    return self._send({"error": "Похоже, это бинарный файл. Его нельзя открыть как текст."}, 415)
                try:
                    content = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    return self._send({"error": "Файл не является текстом UTF-8."}, 415)
                if SECRET_CONTENT.search(content):
                    return self._send({"error": "В файле обнаружен возможный секрет или ключ. Он не будет отправлен ИИ."}, 403)
                return self._send({"path": rel.as_posix(), "content": content, "hash": sha256(raw), "size": len(raw)})
            return self._send({"error": "Маршрут не найден."}, 404)
        except FileNotFoundError as exc:
            return self._send({"error": str(exc)}, 404)
        except PermissionError as exc:
            return self._send({"error": str(exc)}, 403)
        except Exception as exc:
            return self._send({"error": str(exc)}, 400)

    def do_POST(self):
        if not self._authorized():
            return self._send({"error": "Неверный код подключения."}, 401)
        try:
            body = self._body()
            if self.path == "/api/folder":
                global WORKSPACE
                selected = choose_folder(WORKSPACE)
                if selected:
                    if not selected.is_dir():
                        return self._send({"error": "Выбранный путь не является папкой."}, 400)
                    WORKSPACE = selected
                return self._send({"ok": bool(selected), "workspace": str(WORKSPACE) if WORKSPACE else None, "workspaceName": WORKSPACE.name if WORKSPACE else None})
            if self.path == "/api/apply":
                proposed = body.get("files")
                if not isinstance(proposed, list) or not proposed or len(proposed) > 10:
                    return self._send({"error": "Нужно передать от 1 до 10 файлов."}, 400)
                prepared = []
                seen = set()
                for item in proposed:
                    if not isinstance(item, dict) or not isinstance(item.get("content"), str):
                        return self._send({"error": "Некорректное предложение изменения."}, 400)
                    if len(item["content"].encode("utf-8")) > MAX_FILE:
                        return self._send({"error": "Один из файлов больше 1 МБ."}, 413)
                    rel, target = safe_target(item.get("path"), allow_missing=True)
                    key = rel.as_posix()
                    if key in seen:
                        return self._send({"error": f"Файл повторяется в предложении: {key}"}, 400)
                    seen.add(key)
                    exists = target.exists()
                    if exists and not target.is_file():
                        return self._send({"error": f"Путь занят папкой: {key}"}, 409)
                    old_raw = target.read_bytes() if exists else b""
                    old_hash = sha256(old_raw) if exists else None
                    if item.get("expectedHash") != old_hash:
                        return self._send({"error": f"Файл {key} изменился на компьютере после чтения. Обнови его и повтори запрос. Ни один файл не был изменён."}, 409)
                    prepared.append((rel, target, old_raw, exists, item["content"]))
                saved = []
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                # All hashes are checked above before any file is written, preventing partial writes on conflicts.
                for rel, target, old_raw, existed, content in prepared:
                    if existed:
                        backup = WORKSPACE / ".blackgpt-backups" / stamp / rel
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, backup)
                    atomic_write(target, content)
                    saved.append({"path": rel.as_posix(), "hash": sha256(target.read_bytes()), "backupCreated": existed})
                return self._send({"ok": True, "files": saved})
            if self.path == "/api/write":
                raw_path = body.get("path")
                content = body.get("content")
                expected = body.get("expectedHash")
                if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE:
                    return self._send({"error": "Содержимое должно быть текстом размером до 1 МБ."}, 413)
                rel, target = safe_target(raw_path, allow_missing=True)
                exists = target.exists()
                if exists and not target.is_file():
                    return self._send({"error": "Путь уже занят папкой."}, 409)
                current_raw = target.read_bytes() if exists else b""
                current_hash = sha256(current_raw) if exists else None
                if expected != current_hash:
                    return self._send({"error": "Файл изменился на компьютере после чтения. Обнови его в редакторе и повтори, чтобы не затереть чужие изменения."}, 409)
                if exists:
                    backup_root = WORKSPACE / ".blackgpt-backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                    backup_file = backup_root / rel
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup_file)
                atomic_write(target, content)
                new_raw = target.read_bytes()
                return self._send({"ok": True, "path": rel.as_posix(), "hash": sha256(new_raw), "backupCreated": exists})
            return self._send({"error": "Маршрут не найден."}, 404)
        except FileNotFoundError as exc:
            return self._send({"error": str(exc)}, 404)
        except PermissionError as exc:
            return self._send({"error": str(exc)}, 403)
        except Exception as exc:
            return self._send({"error": str(exc)}, 400)


def main():
    global WORKSPACE
    parser = argparse.ArgumentParser(description="Black GPT local workspace agent")
    parser.add_argument("folder", nargs="?", help="Путь к папке проекта (необязательно)")
    args = parser.parse_args()
    if args.folder:
        candidate = Path(args.folder).expanduser().resolve()
        if not candidate.is_dir():
            print("Указанная папка не найдена.")
            sys.exit(2)
        WORKSPACE = candidate
    else:
        WORKSPACE = choose_folder(Path.cwd())
    if not WORKSPACE:
        print("Папка не выбрана. Закрываю помощник.")
        sys.exit(1)

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print("\nBLACK GPT — LOCAL CODE AGENT")
    print("────────────────────────────────────────────")
    print(f"Папка проекта: {WORKSPACE}")
    print(f"Адрес локального помощника: http://{HOST}:{PORT}")
    print("Код подключения (введи его во вкладке Code на сайте):")
    print(TOKEN)
    print("────────────────────────────────────────────")
    print("Окно не закрывай, пока работаешь во вкладке Code.")
    print("Помощник доступен только на этом компьютере и не запускает команды/программы.")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nОстановка Black GPT Local Agent...")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
