# -*- coding: utf-8 -*-
"""
爱给网 (Aigei) 音频批量下载与自动化工具

支持模式：
模式 1（极速多线程下载）：
    读取从浏览器导出的 links.txt 或 songs.json，多线程并发下载音频（MP3 / MIDI）。
模式 2（Playwright 全自动模式）：
    全自动调起浏览器加载网页，注入提取脚本并拦截捕获所有音频直链，全自动下载。
模式 3（本地 HTML 解析）：
    解析本地 页面.html，提取歌曲列表清单。
"""

import os
import re
import sys
import json
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup

# 保证 Windows 控制台 UTF-8 兼容性
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    from tqdm import tqdm
except ImportError:
    class tqdm:
        def __init__(self, total, desc="", unit=""):
            self.total = total
            self.count = 0
            self.desc = desc
        def update(self, n=1):
            self.count += n
            pct = int((self.count / self.total) * 100) if self.total > 0 else 0
            sys.stdout.write(f"\r{self.desc}: {self.count}/{self.total} ({pct}%)")
            sys.stdout.flush()
        def __enter__(self): return self
        def __exit__(self, exc_type, exc_val, exc_tb): print()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
HTML_PATH = os.path.join(BASE_DIR, "页面.html")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    name = re.sub(r'[\r\n\t]', ' ', name)
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = re.sub(r'^\d+[\.\s_-]+', '', name) # 去除已有数字前缀
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:60] if len(name) > 60 else name


def detect_file_extension(url: str, content: bytes = None) -> str:
    """根据 URL 或文件头特征判断音频格式 (mp3 或 mid)"""
    url_lower = url.lower()
    if ".mid" in url_lower or ".midi" in url_lower:
        return "mid"
    if ".mp3" in url_lower:
        return "mp3"
    
    if content and len(content) >= 4:
        if content[:4] == b'MThd':
            return "mid"
        if content[:3] == b'ID3' or (content[0] == 0xFF and (content[1] & 0xE0) == 0xE0):
            return "mp3"

    return "mp3"


def download_single_file(item: dict, output_dir: str, timeout: int = 30) -> bool:
    """下载单个音频文件"""
    title = item.get("title", "未命名")
    url = item.get("url", "")
    idx = item.get("index", 1)
    
    if not url:
        return False

    prefix = f"{idx:02d}"
    clean_title = sanitize_filename(title)
    
    ext = item.get("ext") or detect_file_extension(url)
    target_filename = f"{prefix}. {clean_title}.{ext}"
    target_path = os.path.join(output_dir, target_filename)

    if os.path.exists(target_path) and os.path.getsize(target_path) > 1024:
        return True

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.aigei.com/",
    }

    try:
        resp = requests.get(url, headers=headers, stream=True, timeout=timeout)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "midi" in content_type:
            ext = "mid"
        elif "audio/mpeg" in content_type or "audio/mp3" in content_type:
            ext = "mp3"

        final_path = os.path.join(output_dir, f"{prefix}. {clean_title}.{ext}")

        with open(final_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=32768):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"[-] 下载失败 [{idx}] {title}: {e}")
        return False


def batch_download_from_list(items: list, max_workers: int = 5):
    """多线程批量下载列表中的音频"""
    print(f"\n[+] 准备下载 {len(items)} 个音频，保存目录: {DOWNLOAD_DIR}")
    print(f"[+] 启用并发线程数: {max_workers}\n")

    success_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(download_single_file, item, DOWNLOAD_DIR): item for item in items}
        with tqdm(total=len(items), desc="下载进度", unit="首") as pbar:
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    res = future.result()
                    if res:
                        success_count += 1
                except Exception as e:
                    print(f"[-] 异常: {e}")
                finally:
                    pbar.update(1)

    print(f"\n[OK] 全部任务完成！成功: {success_count}/{len(items)}")
    print(f"[OK] 文件已保存在: {os.path.abspath(DOWNLOAD_DIR)}\n")


def parse_html_songs(html_file: str) -> list:
    """解析页面.html，提取所有歌曲基础元数据"""
    if not os.path.exists(html_file):
        print(f"[-] 找不到 HTML 文件: {html_file}")
        return []

    with open(html_file, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    items = soup.find_all(class_=lambda c: c and "audio-item-box" in c)
    song_list = []
    for idx, item in enumerate(items):
        item_id = item.get("itemid", "") or item.get("itembox", "")
        title_el = item.find(class_=lambda c: c and "title-name" in c)
        title = title_el.get_text(strip=True) if title_el else f"song_{item_id}"
        title = sanitize_filename(title)

        inp = item.find("input", type="hidden")
        token = inp.get("token", "") if inp else ""
        extime = inp.get("extime", "") if inp else ""
        ftype = inp.get("ftype", "") if inp else ""

        song_list.append({
            "index": idx + 1,
            "itemId": item_id,
            "title": title,
            "ftype": ftype,
            "token": token,
            "extime": extime
        })

    return song_list


def run_playwright_automation(url_or_path: str):
    """使用 Playwright 全自动驱动浏览器提取直链并下载"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[-] 未检测到 playwright，请执行: pip install playwright && playwright install chromium")
        return

    js_script_path = os.path.join(BASE_DIR, "browser_downloader.js")
    if not os.path.exists(js_script_path):
        print("[-] 未找到 browser_downloader.js")
        return

    with open(js_script_path, "r", encoding="utf-8") as f:
        js_code = f.read()

    print("\n[+] 正在启动 Chromium 浏览器环境...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        target_url = url_or_path
        if os.path.exists(url_or_path):
            target_url = "file:///" + os.path.abspath(url_or_path).replace("\\", "/")

        print(f"[+] 正在打开页面: {target_url}")
        page.goto(target_url, wait_until="networkidle")
        print("[+] 页面加载完成，注入自动化控制脚本...")
        page.evaluate(js_code)

        print("[+] 控制面板已注入！可以直接在浏览器弹出的面板中点击【🚀 开始提取并下载】。")
        print("[!] 按 Ctrl+C 可关闭浏览器。\n")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[+] 正在关闭浏览器...")
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description="爱给网音频批量下载工具")
    parser.add_argument("--links", "-l", help="从导出的 links.txt 文件中读取下载列表并并发下载")
    parser.add_argument("--json", "-j", help="从导出的 json 清单文件中读取并并发下载")
    parser.add_argument("--parse", "-p", action="store_true", help="解析本地 页面.html 歌曲信息")
    parser.add_argument("--auto", "-a", action="store_true", help="使用 Playwright 启动自动化提取")
    parser.add_argument("--workers", "-w", type=int, default=5, help="下载并发线程数 (默认: 5)")
    args = parser.parse_args()

    # 1. 指定了 links 文件
    if args.links:
        if not os.path.exists(args.links):
            print(f"[-] 文件不存在: {args.links}")
            return
        items = []
        with open(args.links, "r", encoding="utf-8", errors="ignore") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    name, url = parts[0], parts[1]
                    ext = detect_file_extension(url)
                    items.append({"index": idx + 1, "title": name, "url": url, "ext": ext})
                elif line.startswith("http"):
                    items.append({"index": idx + 1, "title": f"audio_{idx+1}", "url": line, "ext": detect_file_extension(line)})
        batch_download_from_list(items, max_workers=args.workers)
        return

    # 2. 指定了 json 文件
    if args.json:
        if not os.path.exists(args.json):
            print(f"[-] 文件不存在: {args.json}")
            return
        with open(args.json, "r", encoding="utf-8") as f:
            items = json.load(f)
        batch_download_from_list(items, max_workers=args.workers)
        return

    # 3. 自动扫描当前目录下是否存在导出的 links*.txt 或 *.json
    found_links = [f for f in os.listdir(BASE_DIR) if f.startswith("aigei_download_links") or f.endswith("links.txt")]
    # 过滤掉 test_links.txt 如果有正式的
    if found_links:
        filepath = os.path.join(BASE_DIR, found_links[0])
        print(f"[+] 检测到下载清单: {found_links[0]}，开始批量下载...")
        items = []
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    name, url = parts[0], parts[1]
                    items.append({"index": idx + 1, "title": name, "url": url, "ext": detect_file_extension(url)})
        if items:
            batch_download_from_list(items, max_workers=args.workers)
            return

    # 4. 自动化模式
    if args.auto:
        run_playwright_automation(HTML_PATH)
        return

    # 5. 解析本地 HTML
    if args.parse or not any([args.links, args.json, args.auto]):
        songs = parse_html_songs(HTML_PATH)
        print(f"[+] 本地 {os.path.basename(HTML_PATH)} 共解析出 {len(songs)} 首歌曲：")
        out_json = os.path.join(BASE_DIR, "songs_manifest.json")
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(songs, f, ensure_ascii=False, indent=2)
        print(f"[OK] 歌曲元数据已保存到: {out_json}")
        print("\n[使用提示]")
        print("  方式 A (最推荐、最简便)：")
        print("    1. 打开浏览器访问爱给网页面，按 F12 打开 Console 控制台。")
        print("    2. 复制 browser_downloader.js 的全部内容，粘贴并回车。")
        print("    3. 页面右下角将出现控制面板，点击【🚀 开始提取并下载】即可！")
        print("  方式 B (极速多线程下载)：")
        print("    在控制面板点击【💾 导出已抓取列表】，将导出的 links.txt 放到 downmidi 目录，")
        print("    运行: python download_music.py 即可享受多线程飞速并发下载！\n")


if __name__ == "__main__":
    main()
