# -*- coding: utf-8 -*-
"""
爱给网 (Aigei) Playwright 全自动音频抓取与下载工具

使用说明：
1. 将在浏览器中复制的 Cookie 粘贴到同目录下的 cookie.txt 中，
   或者直接填写在下方 USER_COOKIE = "..." 双引号内；
2. 运行：
   python auto_downloader.py
   脚本将全自动在后台无头静默运行，批量抓取并下载全部音频（MP3 / MIDI）！
"""

import os
import re
import sys
import json
import time
from urllib.parse import urlparse
import requests
from playwright.sync_api import sync_playwright

# -------------------------------------------------------------
# 方式 1：你可以直接把 Cookie 粘贴在下面双引号内
# （如果在同目录下创建了 cookie.txt，脚本也会自动读取 cookie.txt）
# -------------------------------------------------------------
USER_COOKIE = "audio_play_last_position=246907.601; gei_d_u=1c3032a6b40f4b75b30a9f0cb54d53ea; gei_d_1=d9e38d327d1093e888825685e92499bba00a7b9e7cb43e3fbf2858384024deb3119cccd5904ba1cbc4c90982ab76be4ed19e4efa850f14d27c2be5c8f5a517a8; hhhssi1ill1i=3c7abd880cdbd2af5c356ae502dda865; oOO0OO0oOO00oo0o=true; OooOO000oOOO00o=64871ea542714cb494fab6db34bf85a2; wueiornjk234kj=e09c438fe0d34e7b933298e5e9fb6a61; audio_play_last_position=329000; SESSION=6b7bbb54-5269-4d62-aa22-c734cb4fed08; Hm_lvt_0e0ebfc9c3bdbfdcaa48ccbc43e864f9=1789212915,1789293774,1789370056; HMACCOUNT=03BF5BAF8908C98B; Hm_lpvt_0e0ebfc9c3bdbfdcaa48ccbc43e864f9=1789372033; SERVERID=7a053a6764ffb4a646529948ff8759c9|1789372032|1789370052"

# -------------------------------------------------------------
# 基础配置
# -------------------------------------------------------------
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
COOKIE_FILE = os.path.join(BASE_DIR, "cookie.txt")
USER_DATA_DIR = os.path.join(BASE_DIR, ".browser_session")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(USER_DATA_DIR, exist_ok=True)


def get_cookie_string() -> str:
    """获取用户 Cookie（优先读取 cookie.txt，其次取 USER_COOKIE）"""
    if os.path.exists(COOKIE_FILE):
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
                if content and not content.startswith("#"):
                    return content
        except Exception:
            pass

    return USER_COOKIE.strip()


def parse_cookie_string(cookie_str: str, domain: str = ".aigei.com") -> list:
    """将 Cookie 字符串转换为 Playwright 所需的 cookies 列表"""
    cookie_list = []
    if not cookie_str:
        return cookie_list

    # 去除可能开头的 "Cookie: " 前缀
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
        return True
    except Exception as e:
        print(f"    [✖ 下载失败] {filename}: {e}")
        return False


def run_auto(target_url: str = "https://www.aigei.com/music/midi/", headless: bool = True):
    print("=" * 65)
    print("   爱给网 Playwright 全自动音频抓取与下载工具")
    print(f"   目标页面: {target_url}")
    print(f"   运行模式: {'【无头模式】(后台静默全速运行)' if headless else '【窗口模式】(可视化展示)'}")
    print(f"   保存目录: {DOWNLOAD_DIR}")
    print("=" * 65)

    raw_cookie = get_cookie_string()
    cookie_items = parse_cookie_string(raw_cookie)

    if cookie_items:
        print(f"[+] 成功载入 Cookie！共解析出 {len(cookie_items)} 个键值项。")
    else:
        print("[!] 警告：未检测到有效 Cookie！")
        print("[!] 建议先将浏览器 Cookie 放入同目录的 cookie.txt 文件中。")
        if headless:
            print("[-] 无 Cookie 情况下在无头模式很容易被爱给网拦截登录，切换为窗口模式以便排查...")
            headless = False

    with sync_playwright() as p:
        # 启动 Chromium
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=headless,
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # 注入用户 Cookie
        if cookie_items:
            try:
                context.add_cookies(cookie_items)
                print("[+] 已成功将 Cookie 注入浏览器上下文！")
            except Exception as e:
                print(f"[-] 注入 Cookie 异常: {e}")

        page = context.pages[0] if context.pages else context.new_page()

        # 监听并拦截所有的音频直链响应
        latest_url_box = [None]

        def on_response(response):
            try:
                url = response.url
                # 捕获包含音频直链的响应
                if "aigei.com/src/aud/" in url or ((".mp3" in url or ".mid" in url) and "token=" in url):
                    latest_url_box[0] = url
            except Exception:
                pass

        page.on("response", on_response)

        print("\n[1/4] 正在加载网页，请稍候...")
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
        except Exception as e:
            print(f"[-] 页面加载超时或警告: {e}")

        # 检查是否出现登录弹窗（修复选择器）
        login_text_locator = page.get_by_text("请登录后进行访问")
        has_login = False
        try:
            if login_text_locator.count() > 0 and login_text_locator.first.is_visible():
                has_login = True
        except Exception:
            pass

        if has_login:
            print("\n[!] 提示：页面依然弹出了登录提示！")
            if headless:
                print("[-] 说明提供的 Cookie 可能已失效或过期，请重新复制最新的 Cookie。")
                context.close()
                return
            else:
                print("[*] 请在弹出的浏览器窗口中完成登录，完成后脚本将继续...")
                while True:
                    try:
                        if login_text_locator.count() == 0 or not login_text_locator.first.is_visible():
                            break
                    except Exception:
                        break
                    page.wait_for_timeout(1000)
                print("[+] 登录检测通过！等待 3 秒页面渲染...")
                page.wait_for_timeout(3000)

        # 检查歌曲卡片
        song_cards = page.locator(".audio-item-box")
        total_songs = song_cards.count()
        print(f"\n[2/4] 页面识别完成，共检测到 {total_songs} 首歌曲！")

        if total_songs == 0:
            print("[-] 未能在页面上找到歌曲卡片，可能页面内容未完整渲染。")
            context.close()
            return

        # 提取全部歌曲信息
        songs_info = []
        for i in range(total_songs):
            card = song_cards.nth(i)
            item_id = card.get_attribute("itemid") or card.get_attribute("itembox") or str(i + 1)
            title_el = card.locator(".title-name")
            title = title_el.inner_text().strip() if title_el.count() > 0 else f"歌曲_{item_id}"
            title = sanitize_filename(title)
            songs_info.append({
                "index": i + 1,
                "itemId": item_id,
                "title": title,
                "card": card
            })

        print("\n[3/4] 开始全自动遍历并提取音频真实直链...")
        download_records = []

        for item in songs_info:
            idx = item["index"]
            title = item["title"]
            item_id = item["itemId"]
            card = item["card"]

            print(f"[{idx:02d}/{total_songs:02d}] 正在解析: {title} ...", end="", flush=True)

            latest_url_box[0] = None

            # 滚动到该卡片
            try:
                card.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass

            # 优先调用底层的 fileGet 方法获取播放直链（静音且极快）
            js_ok = page.evaluate("""
                (id) => {
                    const input = document.querySelector('#itemInfoToken_audio_mp3_' + id);
                    if (input && typeof window.fileGet === 'function') {
                        window.fileGet(input, 'play');
                        return true;
                    }
                    return false;
                }
            """, item_id)

            if not js_ok:
                # 备用方案：点击该歌曲的播放按钮
                play_btn = card.locator(".audio-player-btn")
                if play_btn.count() > 0:
                    play_btn.click(timeout=2000)

            # 等待网络响应拦截（最多等 5 秒）
            url = None
            for _ in range(50):
                if latest_url_box[0]:
                    url = latest_url_box[0]
                    break
                page.wait_for_timeout(100)

            if url:
                ext = "mp3"
                if ".mid" in url.lower() or ".midi" in url.lower():
                    ext = "mid"

                filename = f"{idx:02d}. {title}.{ext}"
                print(f" ✔ 直链解析成功 ({ext})")

                download_records.append({
                    "index": idx,
                    "title": title,
                    "filename": filename,
                    "url": url
                })

                # 下载该文件
                download_audio(url, filename)
            else:
                print(" ✖ 未捕获到直链")

            # 安全间隔 18 秒防风控
            page.wait_for_timeout(18000)

        # 导出清单备份
        print("\n[4/4] 导出下载链接清单备份...")
        manifest_path = os.path.join(BASE_DIR, "aigei_download_links.txt")
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write("# 爱给网抓取音频直链列表\n")
            for rec in download_records:
                f.write(f"{rec['filename']}\t{rec['url']}\n")

        print(f"[OK] 链接清单已保存到: {manifest_path}")
        print(f"[OK] 全部任务完成！共成功下载 {len(download_records)}/{total_songs} 首音频。")
        print(f"[OK] 音频保存位置: {os.path.abspath(DOWNLOAD_DIR)}\n")

        context.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="爱给网全自动音频抓取下载工具")
    parser.add_argument("--url", default="https://www.aigei.com/music/midi/", help="目标网页URL")
    parser.add_argument("--gui", action="store_true", help="使用窗口模式运行（查看操作界面）")
    parser.add_argument("--headless", action="store_true", help="强制使用无头模式运行")
    args = parser.parse_args()

    # 默认：只要提供了 cookie 或者是无头，就直接无头运行；如果加了 --gui 则窗口运行
    is_headless = not args.gui
    run_auto(target_url=args.url, headless=is_headless)
