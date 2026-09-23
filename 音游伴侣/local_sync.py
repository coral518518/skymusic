#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音游伴侣 - 本地同步服务 (Local Sync Bridge)
配合油猴脚本使用：接收浏览器下载请求，自动保存乐谱到 scores 目录，并同步维护 downloaded_ids.json
"""

import os
import sys
import json
import re
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# 适配 Windows 控制台输出编码
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCORES_DIR = os.path.join(SCRIPT_DIR, "scores")
INDEX_FILE = os.path.join(SCRIPT_DIR, "downloaded_ids.json")
PORT = 18088

os.makedirs(SCORES_DIR, exist_ok=True)


def sanitize_filename(name: str) -> str:
    clean = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip()
    return clean if clean else "score"


def load_index() -> dict:
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] 读取索引失败: {e}")
    return {"last_updated": "", "total_downloaded": 0, "ids": [], "records": {}}


def save_index(data: dict):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class SyncHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_GET(self):
        if self.path == "/status" or self.path == "/":
            index_data = load_index()
            self._set_headers(200)
            resp = {
                "running": True,
                "total_downloaded": index_data.get("total_downloaded", 0),
                "ids": index_data.get("ids", []),
                "records": index_data.get("records", {}),
            }
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
        else:
            self._set_headers(404)
            self.wfile.write(b'{"error": "not found"}')

    def do_POST(self):
        if self.path == "/save":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(body)
                sid = int(payload.get("id"))
                title = sanitize_filename(payload.get("title", f"score_{sid}"))
                content = payload.get("content", "")

                json_filename = f"{sid}_{title}.json"
                file_path = os.path.join(SCORES_DIR, json_filename)

                # 1. 保存乐谱 JSON 到 scores 目录
                with open(file_path, "w", encoding="utf-8") as f:
                    if isinstance(content, (dict, list)):
                        json.dump(content, f, ensure_ascii=False, indent=2)
                    else:
                        f.write(str(content))

                # 2. 更新维护 downloaded_ids.json
                index_data = load_index()
                id_set = set(index_data.get("ids", []))
                id_set.add(sid)
                index_data["ids"] = sorted(list(id_set))
                index_data["total_downloaded"] = len(index_data["ids"])
                index_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                records = index_data.setdefault("records", {})
                records[str(sid)] = {
                    "title": title,
                    "json_file": json_filename,
                    "download_time": index_data["last_updated"]
                }

                save_index(index_data)

                print(f"[✓ 已同步] ID {sid} 《{title}》 -> {json_filename} (当前总计: {index_data['total_downloaded']} 首)")

                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "id": sid,
                    "title": title,
                    "filename": json_filename,
                    "total_downloaded": index_data["total_downloaded"],
                    "saved_path": file_path
                }, ensure_ascii=False).encode("utf-8"))

            except Exception as e:
                print(f"[!] 保存失败: {e}")
                self._set_headers(500)
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        else:
            self._set_headers(404)
            self.wfile.write(b'{"error": "not found"}')

    def log_message(self, format, *args):
        pass


def run():
    server_address = ("127.0.0.1", PORT)
    httpd = HTTPServer(server_address, SyncHandler)
    print("=" * 60)
    print(f"🎵 音游伴侣本地同步服务已启动: http://127.0.0.1:{PORT}")
    print(f"📁 乐谱保存目录: {SCORES_DIR}")
    print(f"📄 索引记录文件: {INDEX_FILE}")
    print(f"💡 保持此终端开启，在浏览器油猴脚本中点击「下载」时将自动保存文件并维护索引！")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] 服务已停止。")


if __name__ == "__main__":
    run()
