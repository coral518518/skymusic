# -*- coding: utf-8 -*-
"""
爱给网 (Aigei) 全自动音频抓取与自动翻页下载工具 (强化版)

核心特性：
1. 纯内存运行：彻底消除 .browser_session 磁盘缓存垃圾文件；
2. 中文过滤规则：仅下载歌曲名包含中文的音频；
3. ID 级断点记忆：通过 downloaded_ids.txt 记录每首下载过的 ID，彻底防重复；
4. 阶段性自动提交：在 GitHub Actions 运行时，每下载 100 首自动 git commit & push；
5. 瀑布流自动翻页：自动逐页加载与全自动抓取下载。
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
DOWNLOADED_IDS_FILE = os.path.join(BASE_DIR, "downloaded_ids.txt")
SUCCESS_LOG = os.path.join(BASE_DIR, "download_success.txt")
COOKIE_FILE = os.path.join(BASE_DIR, "cookie.txt")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# 默认内置 Cookie
DEFAULT_COOKIE = "audio_play_last_position=246907.601; gei_d_u=1c3032a6b40f4b75b30a9f0cb54d53ea; gei_d_1=d9e38d327d1093e888825685e92499bba00a7b9e7cb43e3fbf2858384024deb3119cccd5904ba1cbc4c90982ab76be4ed19e4efa850f14d27c2be5c8f5a517a8; hhhssi1ill1i=3c7abd880cdbd2af5c356ae502dda865; oOO0OO0oOO00oo0o=true; OooOO000oOOO00o=64871ea542714cb494fab6db34bf85a2; wueiornjk234kj=e09c438fe0d34e7b933298e5e9fb6a61; audio_play_last_position=329000; SESSION=6b7bbb54-5269-4d62-aa22-c734cb4fed08; Hm_lvt_0e0ebfc9c3bdbfdcaa48ccbc43e864f9=1789212915,1789293774,1789370056; HMACCOUNT=03BF5BAF8908C98B; Hm_lpvt_0e0ebfc9c3bdbfdcaa48ccbc43e864f9=1789372033; SERVERID=7a053a6764ffb4a646529948ff8759c9|1789372032|1789370052"


def get_cookie_string() -> str:
    """获取用户 Cookie（环境变量 > cookie.txt > 默认内置）"""
    env_cookie = os.environ.get("AIGEI_COOKIE", "").strip()
    if env_cookie:
        return env_cookie

    if os.path.exists(COOKIE_FILE):
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        return line
        except Exception:
            pass

    return DEFAULT_COOKIE


def parse_cookie_string(cookie_str: str, domain: str = ".aigei.com") -> list:
    """转换 Cookie 格式"""
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
    """净化文件名"""
    name = re.sub(r'[\r\n\t]', ' ', name)
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = re.sub(r'^\d+[\.\s_-]+', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:60] if len(name) > 60 else name


def has_chinese(text: str) -> bool:
    """【规则2】检查文本是否包含中文字符"""
    return bool(re.search(r'[\u4e00-\u9fa5]', text))


def load_downloaded_ids() -> set:
    """【规则3】加载历史已下载的歌曲 ID 集合"""
    ids = set()
    if os.path.exists(DOWNLOADED_IDS_FILE):
        try:
            with open(DOWNLOADED_IDS_FILE, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    item_id = line.strip()
                    if item_id and not item_id.startswith("#"):
                        ids.add(item_id)
        except Exception:
            pass
    return ids


def save_downloaded_id(item_id: str):
    """【规则3】即时持久化记录已下载的歌曲 ID"""
    try:
        with open(DOWNLOADED_IDS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{item_id}\n")
    except Exception as e:
        print(f"[-] 保存 ID 异常: {e}")


def git_auto_commit_push(downloaded_count: int):
    """【规则4】GitHub Actions 自动阶段性提交与推送"""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return

    print(f"\n[🚀 触发阶段性自动提交] 已累计新下载 {downloaded_count} 首，正在提交至 GitHub 仓库...")
    try:
        os.system('git config user.name "github-actions[bot]"')
        os.system('git config user.email "github-actions[bot]@users.noreply.github.com"')
        os.system('git add downmidi/downloads/ downmidi/downloaded_ids.txt downmidi/download_success.txt')
        msg = f"chore: 自动阶段性提交 - 累计下载 {downloaded_count} 首音频 [skip ci]"
        os.system(f'git commit -m "{msg}"')
        os.system('git pull --rebase || true')
        os.system('git push || true')
        print("[✔ 阶段性自动推送完成！成果已稳妥保存在仓库]\n")
    except Exception as e:
        print(f"[-] 自动推送异常: {e}\n")


def download_audio(url: str, filename: str) -> bool:
    """下载音频文件"""
    target_path = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(target_path) and os.path.getsize(target_path) > 1024:
        print(f"    [本地文件已存在跳过] {filename}")
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
        
        with open(SUCCESS_LOG, "a", encoding="utf-8") as f:
            f.write(f"{filename}\t{url}\n")
        return True
    except Exception as e:
        print(f"    [✖ 下载失败] {filename}: {e}")
        return False


def run_crawler(target_url: str = "https://www.aigei.com/music/midi/",
                max_pages: int = 3,
                delay: float = 3.0,
                push_interval: int = 100,
                headless: bool = True):
    print("=" * 65)
    print("   爱给网 Playwright 全自动抓取与自动翻页工具 (强化版)")
    print(f"   目标页面: {target_url}")
    print(f"   计划抓取页数: {'全部翻页至末尾' if max_pages <= 0 else f'{max_pages} 页 (约 {max_pages * 25} 首)'}")
    print(f"   请求安全延迟: {delay} 秒")
    print(f"   自动提交阈值: 每下载 {push_interval} 首自动 git push")
    print(f"   过滤规则: 【歌曲名必须包含中文】")
    print(f"   运行模式: {'【无头模式 (后台运行)】' if headless else '【窗口模式】'}")
    print(f"   保存目录: {DOWNLOAD_DIR}")
    print("=" * 65)

    # 1. 加载历史已下载 ID
    downloaded_ids = load_downloaded_ids()
    print(f"[+] 历史已下载记录: 共检测到 {len(downloaded_ids)} 个已有歌曲 ID，将自动跳过防重复！")

    # 2. 准备 Cookie
    raw_cookie = get_cookie_string()
    cookie_items = parse_cookie_string(raw_cookie)
    if cookie_items:
        print(f"[+] 成功载入 Cookie！共 {len(cookie_items)} 个键值项。")
    else:
        print("[!] 警告：未检测到有效 Cookie！")

    with sync_playwright() as p:
        # 3. 纯内存模式启动（彻底消灭 .browser_session 磁盘缓存垃圾文件）
        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled", # 核心反反爬指纹
            "--disable-infobars",
            "--window-size=1920,1080",
        ]

        browser = p.chromium.launch(
            headless=headless,
            args=launch_args
        )

        context = browser.new_context(
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

        page = context.new_page()

        # 覆盖 navigator.webdriver
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
            print("[!] 网站依然要求登录！说明 Cookie 已失效，请更新 Cookie。")
            if headless:
                context.close()
                browser.close()
                return

        total_new_downloaded = 0
        current_page = 1
        processed_page_ids = set()

        print("\n[2/3] 开始全自动分页抓取与下载...")

        while True:
            print(f"\n>>> 正在处理第 {current_page} 页...")

            # 滚动加载新卡片（翻页）
            if current_page > 1:
                print(f"[+] 滚动页面底部触发翻页加载 (Page {current_page})...")
                prev_count = page.locator(".audio-item-box").count()
                
                # 触发滚动
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                
                # 等待新卡片渲染加载
                loaded = False
                for _ in range(30):
                    page.wait_for_timeout(1500)
                    now_count = page.locator(".audio-item-box").count()
                    if now_count > prev_count:
                        loaded = True
                        break
                
                if not loaded:
                    print(f"[-] 滚动后未检测到新歌曲卡片，已到达最后一页。")
                    break

            cards = page.locator(".audio-item-box")
            card_count = cards.count()
            print(f"[+] 当前页面累计共有 {card_count} 首歌曲卡片。")

            # 提取本页新增卡片
            new_cards = []
            for i in range(card_count):
                c = cards.nth(i)
                item_id = c.get_attribute("itemid") or c.get_attribute("itembox")
                if item_id and item_id not in processed_page_ids:
                    processed_page_ids.add(item_id)
                    title_el = c.locator(".title-name")
                    title = title_el.inner_text().strip() if title_el.count() > 0 else f"歌曲_{item_id}"
                    new_cards.append({
                        "id": item_id,
                        "title": sanitize_filename(title),
                        "card": c,
                        "global_idx": len(processed_page_ids)
                    })

            print(f"[+] 本页扫描到 {len(new_cards)} 首新歌曲")

            # 逐首处理与下载
            for song in new_cards:
                song_id = song["id"]
                title = song["title"]
                card = song["card"]
                g_idx = song["global_idx"]

                # 规则 2 检查：必须包含中文
                if not has_chinese(title):
                    print(f"  [{g_idx:03d}] [跳过-非中文歌名] {title}")
                    continue

                # 规则 3 检查：历史已下载 ID 防重复
                if song_id in downloaded_ids:
                    print(f"  [{g_idx:03d}] [跳过-已在历史记录中] ID: {song_id} - {title}")
                    continue

                print(f"  [{g_idx:03d}] 开始解析: {title} (ID: {song_id}) ...", end="", flush=True)

                latest_url_box[0] = None

                # 模拟点击播放按钮获取直链
                play_btn = card.locator(".audio-player-btn")
                clicked = False
                try:
                    if play_btn.count() > 0:
                        play_btn.click(timeout=2000)
                        clicked = True
                except Exception:
                    pass

                if not clicked:
                    page.evaluate("""
                        (id) => {
                            const inp = document.querySelector('#itemInfoToken_audio_mp3_' + id);
                            if (inp && typeof window.fileGet === 'function') {
                                window.fileGet(inp, 'play');
                            }
                        }
                    """, song_id)

                # 等待直链返回（最多等 10 秒）
                url = None
                for _ in range(100):
                    if latest_url_box[0]:
                        url = latest_url_box[0]
                        break
                    page.wait_for_timeout(100)

                if url:
                    ext = "mp3"
                    if ".mid" in url.lower() or ".midi" in url.lower():
                        ext = "mid"

                    filename = f"{g_idx:03d}. {title}.{ext}"
                    print(f" ✔ 直链获取成功 ({ext})")
                    
                    if download_audio(url, filename):
                        total_new_downloaded += 1
                        # 规则 3：成功下载后，立即记录 ID
                        downloaded_ids.add(song_id)
                        save_downloaded_id(song_id)

                        # 规则 4：达到设定阈值自动提交到 GitHub
                        if total_new_downloaded > 0 and total_new_downloaded % push_interval == 0:
                            git_auto_commit_push(total_new_downloaded)
                else:
                    print(" ✖ 直链捕获超时")

                # 防风控安全间隔
                if delay > 0:
                    page.wait_for_timeout(int(delay * 1000))

            # 翻页限制判定
            if max_pages > 0 and current_page >= max_pages:
                print(f"\n[✔] 已达到设定的抓取页数上限 ({max_pages} 页)，正常结束抓取。")
                break

            current_page += 1

        # 任务结束时的最终提交（如有未推送的内容）
        if total_new_downloaded > 0 and total_new_downloaded % push_interval != 0:
            git_auto_commit_push(total_new_downloaded)

        print("\n" + "=" * 65)
        print(f"[3/3] 任务执行完毕！")
        print(f"      本次累计新下载: {total_new_downloaded} 首")
        print(f"      总已下载歌曲库: {len(downloaded_ids)} 首")
        print(f"      音频保存路径:   {os.path.abspath(DOWNLOAD_DIR)}")
        print("=" * 65 + "\n")

        context.close()
        browser.close()


def main():
    parser = argparse.ArgumentParser(description="爱给网全自动音频抓取与自动翻页工具 (强化版)")
    parser.add_argument("--url", default="https://www.aigei.com/music/midi/", help="目标网页URL")
    parser.add_argument("--pages", "-p", type=int, default=3, help="抓取翻页数量 (默认 3 页，设为 0 则一直翻到末尾)")
    parser.add_argument("--delay", "-d", type=float, default=3.0, help="每首歌安全间隔延迟 (秒，默认 3.0)")
    parser.add_argument("--push-interval", type=int, default=100, help="在 GitHub Actions 运行时每下载多少首自动 push (默认 100)")
    parser.add_argument("--gui", action="store_true", help="使用窗口模式运行 (默认无头)")
    parser.add_argument("--headless", action="store_true", help="强制无头运行")
    args = parser.parse_args()

    is_headless = not args.gui
    run_crawler(
        target_url=args.url,
        max_pages=args.pages,
        delay=args.delay,
        push_interval=args.push_interval,
        headless=is_headless
    )


if __name__ == "__main__":
    main()
