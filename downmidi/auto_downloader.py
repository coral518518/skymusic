# -*- coding: utf-8 -*-
"""
爱给网 (Aigei) Playwright 全自动音频抓取与自动翻页下载工具

支持功能：
1. 自动注入 Cookie，绕过登录弹窗；
2. 自动瀑布流翻页（支持指定翻页数量或翻到末尾）；
3. 捕获试听播放直链（MP3 / MIDI）；
4. 断点续传，已下载音频自动跳过；
5. 完美适配本地环境与 GitHub Actions（结合 Xvfb 虚拟显示器与反反爬指纹）。
"""

import os
import re
import sys
import json
import time
import argparse
from urllib.parse import urlparse
import requests
from playwright.sync_api import sync_playwright

# 保证 Windows 控制台 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
USER_DATA_DIR = os.path.join(BASE_DIR, ".browser_session")
SUCCESS_LOG = os.path.join(BASE_DIR, "download_success.txt")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(USER_DATA_DIR, exist_ok=True)


def get_cookie_string() -> str:
    """获取用户 Cookie（环境变量 > cookie.txt）"""
    # 优先从环境变量中读取（适用于 GitHub Actions Secrets）
    env_cookie = os.environ.get("AIGEI_COOKIE", "").strip()
    if env_cookie:
        return env_cookie

    return "audio_play_last_position=246907.601; gei_d_u=1c3032a6b40f4b75b30a9f0cb54d53ea; gei_d_1=d9e38d327d1093e888825685e92499bba00a7b9e7cb43e3fbf2858384024deb3119cccd5904ba1cbc4c90982ab76be4ed19e4efa850f14d27c2be5c8f5a517a8; hhhssi1ill1i=3c7abd880cdbd2af5c356ae502dda865; oOO0OO0oOO00oo0o=true; OooOO000oOOO00o=64871ea542714cb494fab6db34bf85a2; wueiornjk234kj=e09c438fe0d34e7b933298e5e9fb6a61; audio_play_last_position=329000; SESSION=6b7bbb54-5269-4d62-aa22-c734cb4fed08; Hm_lvt_0e0ebfc9c3bdbfdcaa48ccbc43e864f9=1789212915,1789293774,1789370056; HMACCOUNT=03BF5BAF8908C98B; Hm_lpvt_0e0ebfc9c3bdbfdcaa48ccbc43e864f9=1789372033; SERVERID=7a053a6764ffb4a646529948ff8759c9|1789372032|1789370052"



def parse_cookie_string(cookie_str: str, domain: str = ".aigei.com") -> list:
    """将 Cookie 字符串转换为 Playwright 所需的 cookies 列表"""
    cookie_list = []
    if not cookie_str:
        return cookie_list

    if cookie_str.lower().startswith("cookie:"):
        cookie_str = cookie_str[7:].strip()

    items = cookie_str.split(";")
    for item in items:
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, val = item.split("=", 1)
        name = name.strip()
        val = val.strip()
        if name:
            cookie_list.append({
                "name": name,
                "value": val,
                "domain": domain,
                "path": "/"
            })
    return cookie_list


def sanitize_filename(name: str) -> str:
    """文件名安全过滤"""
    name = re.sub(r'[\r\n\t]', ' ', name)
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = re.sub(r'^\d+[\.\s_-]+', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:60] if len(name) > 60 else name


def download_audio(url: str, filename: str) -> bool:
    """下载音频文件"""
    target_path = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(target_path) and os.path.getsize(target_path) > 1024:
        print(f"    [已存在跳过] {filename}")
        return True

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.aigei.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        with open(target_path, "wb") as f:
            f.write(resp.content)
        print(f"    [✔ 下载成功] {filename} ({len(resp.content)} 字节)")
        
        # 追加记录
        with open(SUCCESS_LOG, "a", encoding="utf-8") as f:
            f.write(f"{filename}\t{url}\n")
        return True
    except Exception as e:
        print(f"    [✖ 下载失败] {filename}: {e}")
        return False


def run_crawler(target_url: str = "https://www.aigei.com/music/midi/",
                max_pages: int = 3,
                delay: float = 3.0,
                headless: bool = True):
    print("=" * 65)
    print("   爱给网 Playwright 全自动音频抓取与自动翻页工具")
    print(f"   目标页面: {target_url}")
    print(f"   计划抓取页数: {'全部翻页至末尾' if max_pages <= 0 else f'{max_pages} 页 (约 {max_pages * 25} 首)'}")
    print(f"   请求安全延迟: {delay} 秒")
    print(f"   运行模式: {'【无头模式】' if headless else '【可视化窗口模式】'}")
    print(f"   保存目录: {DOWNLOAD_DIR}")
    print("=" * 65)

    raw_cookie = get_cookie_string()
    cookie_items = parse_cookie_string(raw_cookie)

    if cookie_items:
        print(f"[+] 成功载入 Cookie！共 {len(cookie_items)} 个键值项。")
    else:
        print("[!] 警告：未检测到有效 Cookie！请检查 cookie.txt 或 AIGEI_COOKIE 环境变量。")

    with sync_playwright() as p:
        # 启动 Chromium 浏览器，配置防反爬参数
        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled", # 隐藏自动化特征
            "--disable-infobars",
            "--window-size=1920,1080",
        ]

        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=headless,
            args=launch_args,
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # 注入用户 Cookie
        if cookie_items:
            try:
                context.add_cookies(cookie_items)
                print("[+] 已成功注入 Cookie 到浏览器！")
            except Exception as e:
                print(f"[-] 注入 Cookie 失败: {e}")

        page = context.pages[0] if context.pages else context.new_page()

        # 覆盖 navigator.webdriver 防止检测
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # 监听音频真实直链
        latest_url_box = [None]

        def on_response(response):
            try:
                url = response.url
                if "aigei.com/src/aud/" in url or ((".mp3" in url or ".mid" in url) and "token=" in url):
                    latest_url_box[0] = url
            except Exception:
                pass

        page.on("response", on_response)

        print("\n[1/3] 正在加载首页建立会话...")
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"[-] 页面加载异常: {e}")

        # 检查登录弹窗
        login_text_locator = page.get_by_text("请登录后进行访问")
        if login_text_locator.count() > 0 and login_text_locator.first.is_visible():
            print("[!] 网站依然要求登录！说明 Cookie 已失效或未登录，请更新 Cookie。")
            if headless:
                context.close()
                return

        # 统计已下载列表以断点续传
        downloaded_titles = set()
        if os.path.exists(SUCCESS_LOG):
            try:
                with open(SUCCESS_LOG, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        parts = line.strip().split("\t")
                        if parts:
                            downloaded_titles.add(parts[0])
            except Exception:
                pass

        total_downloaded = 0
        current_page = 1
        processed_item_ids = set()

        print("\n[2/3] 开始全自动分页抓取与下载...")

        while True:
            print(f"\n>>> 正在处理第 {current_page} 页...")

            # 滚动加载新卡片（翻页）
            if current_page > 1:
                print(f"[+] 滚动页面底部触发翻页请求 (Page {current_page})...")
                prev_count = page.locator(".audio-item-box").count()
                
                # 触发滚动
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                
                # 等待新卡片加载出来
                loaded = False
                for _ in range(30):
                    page.wait_for_timeout(500)
                    now_count = page.locator(".audio-item-box").count()
                    if now_count > prev_count:
                        loaded = True
                        break
                
                if not loaded:
                    print(f"[-] 滚动后未检测到新歌曲卡片，可能已到达最后一页。")
                    break

            # 获取当前页面中所有歌曲卡片
            cards = page.locator(".audio-item-box")
            card_count = cards.count()
            print(f"[+] 当前页面共有 {card_count} 首歌曲卡片。")

            # 筛选未处理的歌曲
            new_cards = []
            for i in range(card_count):
                c = cards.nth(i)
                item_id = c.get_attribute("itemid") or c.get_attribute("itembox")
                if item_id and item_id not in processed_item_ids:
                    processed_item_ids.add(item_id)
                    title_el = c.locator(".title-name")
                    title = title_el.inner_text().strip() if title_el.count() > 0 else f"歌曲_{item_id}"
                    new_cards.append({
                        "id": item_id,
                        "title": sanitize_filename(title),
                        "card": c,
                        "global_idx": len(processed_item_ids)
                    })

            print(f"[+] 本页待下载新歌曲: {len(new_cards)} 首")

            # 遍历下载本页的新歌曲
            for song in new_cards:
                song_id = song["id"]
                title = song["title"]
                card = song["card"]
                g_idx = song["global_idx"]

                print(f"  [{g_idx:03d}] 解析: {title} ...", end="", flush=True)

                latest_url_box[0] = None

                # 优先点击播放按钮捕获直链
                play_btn = card.locator(".audio-player-btn")
                clicked = False
                try:
                    if play_btn.count() > 0:
                        play_btn.click(timeout=2000)
                        clicked = True
                except Exception:
                    pass

                if not clicked:
                    # 备用方案：通过 DOM 触发 fileGet
                    page.evaluate("""
                        (id) => {
                            const inp = document.querySelector('#itemInfoToken_audio_mp3_' + id);
                            if (inp && typeof window.fileGet === 'function') {
                                window.fileGet(inp, 'play');
                            }
                        }
                    """, song_id)

                # 等待直链返回（最多 6 秒）
                url = None
                for _ in range(60):
                    if latest_url_box[0]:
                        url = latest_url_box[0]
                        break
                    page.wait_for_timeout(100)

                if url:
                    ext = "mp3"
                    if ".mid" in url.lower() or ".midi" in url.lower():
                        ext = "mid"

                    filename = f"{g_idx:03d}. {title}.{ext}"
                    print(f" ✔ 获得直链 ({ext})")
                    
                    if download_audio(url, filename):
                        total_downloaded += 1
                else:
                    print(" ✖ 直链捕获超时")

                # 防风控安全间隔
                if delay > 0:
                    page.wait_for_timeout(int(delay * 1000))

            # 检查是否满足最大页数限制
            if max_pages > 0 and current_page >= max_pages:
                print(f"\n[✔] 已达到指定的抓取页数限制 ({max_pages} 页)，停止抓取。")
                break

            current_page += 1

        print("\n" + "=" * 65)
        print(f"[3/3] 任务全部完成！")
        print(f"      共扫描歌曲: {len(processed_item_ids)} 首")
        print(f"      成功下载:   {total_downloaded} 首")
        print(f"      保存路径:   {os.path.abspath(DOWNLOAD_DIR)}")
        print("=" * 65 + "\n")

        context.close()


def main():
    parser = argparse.ArgumentParser(description="爱给网全自动音频抓取与自动翻页工具")
    parser.add_argument("--url", default="https://www.aigei.com/music/midi/", help="目标网页URL")
    parser.add_argument("--pages", "-p", type=int, default=3, help="抓取翻页数量 (默认 3 页，设为 0 则一直翻到末尾)")
    parser.add_argument("--delay", "-d", type=float, default=3.0, help="每首歌安全间隔延迟 (秒，默认 3.0)")
    parser.add_argument("--gui", action="store_true", help="使用窗口模式运行 (默认无头)")
    parser.add_argument("--headless", action="store_true", help="强制无头运行")
    args = parser.parse_args()

    is_headless = not args.gui
    run_crawler(
        target_url=args.url,
        max_pages=args.pages,
        delay=args.delay,
        headless=is_headless
    )


if __name__ == "__main__":
    main()
