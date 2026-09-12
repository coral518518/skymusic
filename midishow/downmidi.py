import os
import re
import sys
import time
import random
import subprocess
from playwright.sync_api import sync_playwright

# 基础路径与文件配置（保证无论在哪个目录下运行，都写入仓库根目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "midishow" else SCRIPT_DIR

CATEGORY_URL = os.environ.get("CATEGORY_URL", "https://www.midishow.com/midi/browse/pop-music")
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", os.path.join(REPO_ROOT, "midi_downloads"))
SUCCESS_LOG = os.environ.get("SUCCESS_LOG", os.path.join(REPO_ROOT, "downloaded_success.txt"))
FAIL_LOG = os.environ.get("FAIL_LOG", os.path.join(REPO_ROOT, "downloaded_failed.txt"))

START_PAGE = int(os.environ.get("START_PAGE", 1))
MAX_PAGE = int(os.environ.get("MAX_PAGE", 500000))
PUSH_INTERVAL = int(os.environ.get("PUSH_INTERVAL", 10))
HEADLESS = os.environ.get("HEADLESS", "true" if os.environ.get("CI") else "false").lower() == "true"
AUTO_GIT_PUSH = os.environ.get("AUTO_GIT_PUSH", "true").lower() == "true"
PROXY_SERVER = os.environ.get("PROXY_SERVER") or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Cookie 字符串：默认保留有效登录会话，支持环境变量传入最新 cf_clearance (适用于 GitHub Secrets)
DEFAULT_COOKIE_STR = "PHPSESSID=et8mol59odq7tj6f7k04oukepp; _csrf=35368ea1bd944a2594f915aa83947bf96babc6ba9bd55f09c586df4ecc4966d0a%3A2%3A%7Bi%3A0%3Bs%3A5%3A%22_csrf%22%3Bi%3A1%3Bs%3A32%3A%22Z1D9rdpnzbXqeefx0Z1Gun2zyrMtI2jD%22%3B%7D; _language=4be5658c4b69d6d6d0f856ff1d2abd82d33f89ab530702899ed361532fae4a24a%3A2%3A%7Bi%3A0%3Bs%3A9%3A%22_language%22%3Bi%3A1%3Bs%3A2%3A%22zh%22%3B%7D"
COOKIE_STR = os.environ.get("MIDISHOW_COOKIE") or DEFAULT_COOKIE_STR

# 抹除自动化浏览器特征指纹
STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});
window.chrome = { runtime: {} };
"""

# 核心 Hook 脚本：在页面初始化阶段注入，拦截 JZZ 解析时的二进制数据
HOOK_SCRIPT = """
window._midiQueue = [];
(function() {
    function hookJZZ() {
        if (window.JZZ && window.JZZ.MIDI && window.JZZ.MIDI.SMF) {
            const oldFunc = window.JZZ.MIDI.SMF;
            window.JZZ.MIDI.SMF = function(...args) {
                const h1tag = document.querySelector("h1.font-size-2.mb-1.pl-md-player");
                const title = h1tag ? h1tag.textContent.trim() : "unknown";
                
                const rawStr = args[0] || "";
                const bytes = [];
                for (let i = 0; i < rawStr.length; i++) {
                    bytes.push(rawStr.charCodeAt(i) & 0xff);
                }
                window._midiQueue.push({
                    title: title,
                    bytes: bytes
                });
                return oldFunc(...args);
            };
            return true;
        }
        return false;
    }

    if (!hookJZZ()) {
        const timer = setInterval(() => {
            if (hookJZZ()) clearInterval(timer);
        }, 30);
    }
})();
"""

def parse_cookies(cookie_str, domain=".midishow.com"):
    cookies = []
    for item in cookie_str.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        cookies.append({
            "name": k.strip(),
            "value": v.strip(),
            "domain": domain,
            "path": "/"
        })
    return cookies

def load_done_ids():
    if not os.path.exists(SUCCESS_LOG):
        return set()
    with open(SUCCESS_LOG, "r", encoding="utf-8") as f:
        return {line.strip().split("\t")[0] for line in f if line.strip()}

def log_result(file, mid, title, msg=""):
    with open(file, "a", encoding="utf-8") as f:
        f.write(f"{mid}\t{title}\t{time.strftime('%Y-%m-%d %H:%M:%S')}\t{msg}\n")

def git_commit_and_push(page_num, is_final=False):
    """自动提交并推送到 GitHub 仓库"""
    if not AUTO_GIT_PUSH:
        return

    try:
        rel_files = [
            os.path.relpath(DOWNLOAD_DIR, REPO_ROOT),
            os.path.relpath(SUCCESS_LOG, REPO_ROOT),
            os.path.relpath(FAIL_LOG, REPO_ROOT)
        ]
        status = subprocess.run(
            ["git", "status", "--porcelain"] + rel_files,
            capture_output=True, text=True, cwd=REPO_ROOT
        )
        if not status.stdout.strip():
            print(f"[*] Git 检查：暂无新增 MIDI 文件或日志需要提交 (第 {page_num} 页)。")
            return

        print(f"\n[Git] 检测到新增成果，正在自动提交并推送到 GitHub (进度: 第 {page_num} 页)...")
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=REPO_ROOT, check=False)
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], cwd=REPO_ROOT, check=False)

        subprocess.run(["git", "add"] + rel_files, cwd=REPO_ROOT, check=True)
        
        tag = f"第 {page_num} 页" if not is_final else "全部完成"
        msg = f"chore: 自动保存 MIDI 下载成果与日志 ({tag}) [skip ci]"
        subprocess.run(["git", "commit", "-m", msg], cwd=REPO_ROOT, check=True)

        # 尝试拉取并推送
        subprocess.run(["git", "pull", "--rebase"], cwd=REPO_ROOT, check=False)
        push_res = subprocess.run(["git", "push"], capture_output=True, text=True, cwd=REPO_ROOT)
        if push_res.returncode == 0:
            print(f"[Git] ✓ 成功将最新进度推送到 GitHub 仓库！\n")
        else:
            print(f"[Git] ! 推送失败 (暂不影响抓取，稍后重试): {push_res.stderr.strip()[:200]}\n")
    except Exception as e:
        print(f"[Git] ! 自动提交流程异常 (跳过继续下载): {e}\n")

def handle_cf_challenge(page, max_retries=3):
    """检测并穿透 Cloudflare 挑战页（参考 UC 模式思想：多特征识别 + 真实坐标模拟点击）"""
    for attempt in range(max_retries):
        title = ""
        try:
            title = page.title().lower()
        except Exception:
            pass
            
        cur_url = page.url.lower()
        body_text = ""
        try:
            body_text = page.evaluate("() => document.body ? document.body.innerText.slice(0, 300).toLowerCase() : ''")
        except Exception:
            pass
            
        is_cf = (
            "just a moment" in title
            or "checking your browser" in body_text
            or "challenges.cloudflare.com" in cur_url
            or "cf-wrapper" in body_text
            or "ray id" in body_text
        )
        
        if not is_cf:
            return True
            
        print(f"  [CF] 检测到 Cloudflare 验证挑战 (第 {attempt + 1}/{max_retries} 次)，尝试自动穿透...")
        time.sleep(2)
        
        # 查找 Turnstile 验证框 iframe 并用真实鼠标坐标点击 (类似 uc_gui_click_captcha)
        clicked = False
        for frame in page.frames:
            if "challenges.cloudflare.com" in frame.url:
                try:
                    cb = frame.locator('input[type="checkbox"], .ctp-checkbox-label, #challenge-stage').first
                    if cb.count() > 0:
                        box = cb.bounding_box()
                        if box:
                            print(f"  [CF] 找到 Turnstile 复选框，坐标 ({int(box['x'])}, {int(box['y'])})，触发真实物理点击...")
                            page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                            clicked = True
                            time.sleep(5)
                            break
                except Exception as e:
                    pass
                    
        if not clicked:
            time.sleep(3)
            
    final_title = page.title().lower()
    return "just a moment" not in final_title

def create_browser_context(browser):
    """创建统一配置的浏览器上下文（包含视口、代理与 Cookie）"""
    context_kwargs = {
        "viewport": {'width': 1920, 'height': 1080},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
    if PROXY_SERVER:
        context_kwargs["proxy"] = {"server": PROXY_SERVER}
    context = browser.new_context(**context_kwargs)
    if COOKIE_STR.strip():
        context.add_cookies(parse_cookies(COOKIE_STR))
    return context

def ensure_page_ready(browser, context, page):
    """页面健康检查与自愈机制：若页面意外关闭则自动恢复"""
    try:
        if page is None or page.is_closed():
            page = context.new_page()
            page.add_init_script(STEALTH_SCRIPT)
            page.add_init_script(HOOK_SCRIPT)
    except Exception:
        context = create_browser_context(browser)
        page = context.new_page()
        page.add_init_script(STEALTH_SCRIPT)
        page.add_init_script(HOOK_SCRIPT)
    return context, page

def main():
    done_ids = load_done_ids()
    print(f"[*] 已成功下载 {len(done_ids)} 首，开始自动运行...")
    print(f"[*] 抓取范围: 第 {START_PAGE} 页 至 第 {MAX_PAGE} 页 (每 {PUSH_INTERVAL} 页自动提交一次)")
    if PROXY_SERVER:
        print(f"[*] 网络代理已启用: {PROXY_SERVER}")

    launch_kwargs = {
        "headless": HEADLESS,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox"
        ]
    }
    if PROXY_SERVER:
        launch_kwargs["proxy"] = {"server": PROXY_SERVER}

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        context = create_browser_context(browser)
        page = context.new_page()
        page.add_init_script(STEALTH_SCRIPT)
        page.add_init_script(HOOK_SCRIPT)

        consecutive_cf_blocks = 0

        for current_page in range(START_PAGE, MAX_PAGE + 1):
            print(f"\n===== 开始抓取第 {current_page} 页 =====")
            list_url = f"{CATEGORY_URL}?page={current_page}"
            
            # 列表页容错与重试
            loaded_list = False
            for retry in range(3):
                try:
                    context, page = ensure_page_ready(browser, context, page)
                    page.goto(list_url, wait_until="domcontentloaded", timeout=30000)
                    
                    # 检测并穿透 Cloudflare 盾
                    if handle_cf_challenge(page):
                        loaded_list = True
                        break
                    else:
                        print(f"  [!] 第 {current_page} 页未能穿透 Cloudflare 拦截 (尝试 {retry + 1}/3)")
                        time.sleep(3)
                except Exception as e:
                    print(f"[!] 访问列表页失败 (尝试 {retry + 1}/3): {e}")
                    time.sleep(3)

            if not loaded_list:
                consecutive_cf_blocks += 1
                print(f"[!] 第 {current_page} 页被 Cloudflare 拦截或无法访问 (连续 {consecutive_cf_blocks} 次)。")
                if consecutive_cf_blocks >= 5:
                    print("\n" + "=" * 65)
                    print("[!] 致命提示：已连续 5 页被 Cloudflare 验证盾拦截！")
                    print("[!] 原因：当前 Cookie 中的 cf_clearance 已失效，或云端 IP 触发安全防护。")
                    print("[!] 解决方案：")
                    print("    1. 在浏览器登录 midishow.com，按 F12 -> Application -> Cookies")
                    print("    2. 复制最新的完整 Cookie (必须包含 cf_clearance 和 PHPSESSID)")
                    print("    3. 在 GitHub 仓库 Settings -> Secrets -> Actions 中更新 MIDISHOW_COOKIE")
                    print("    4. 或在 Action 页面手动触发时，在 '自定义 Cookie' 输入框中粘贴")
                    print("=" * 65 + "\n")
                    break
                continue

            # 提取本页所有歌曲链接
            links = page.locator('a[href*="/midi/"]').all()
            page_ids = []
            for link in links:
                href = link.get_attribute("href") or ""
                match = re.search(r'/midi/(\d+)\.html', href)
                if match and match.group(1) not in page_ids:
                    page_ids.append(match.group(1))

            if not page_ids:
                consecutive_cf_blocks += 1
                print(f"[!] 第 {current_page} 页未提取到歌曲 ID (可能被盾拦截或已是最后一页)。")
                if consecutive_cf_blocks >= 5:
                    print("\n[!] 连续 5 页未解析到歌曲，提前终止任务以防空跑。请检查 Cookie 或网络。")
                    break
                continue

            consecutive_cf_blocks = 0
            print(f"[*] 解析到 {len(page_ids)} 首歌曲")

            for idx, mid in enumerate(page_ids, start=1):
                if mid in done_ids:
                    print(f"  [{idx}/{len(page_ids)}] ID:{mid} 已下载，跳过")
                    continue

                song_url = f"https://www.midishow.com/midi/{mid}.html"
                try:
                    context, page = ensure_page_ready(browser, context, page)
                    # 1. 打开歌曲详情页
                    page.goto(song_url, wait_until="domcontentloaded", timeout=25000)
                    handle_cf_challenge(page)
                    page.evaluate("window._midiQueue = [];")  # 清空队列

                    # 2. 定位并点击当前可见的播放按钮
                    play_btn = page.locator("button.j-play:visible, button.ms-player-play:visible").first
                    try:
                        play_btn.wait_for(state="visible", timeout=6000)
                        play_btn.click()
                    except Exception:
                        # 兜底：直接通过 JS 触发点击
                        page.evaluate("document.querySelector('button.j-play, button.ms-player-play')?.click()")

                    # 3. 等待 Hook 截获到数据（最多等待 10 秒）
                    page.wait_for_function("window._midiQueue && window._midiQueue.length > 0", timeout=10000)
                    midi_data = page.evaluate("window._midiQueue.shift()")

                    # 4. 写入本地文件
                    title = midi_data.get("title", f"midi_{mid}")
                    safe_title = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", title).strip() or f"midi_{mid}"
                    filepath = os.path.join(DOWNLOAD_DIR, f"{safe_title}_{mid}.mid")

                    with open(filepath, "wb") as f:
                        f.write(bytes(midi_data["bytes"]))

                    print(f"  [{idx}/{len(page_ids)}] [成功] ID:{mid} -> {safe_title}.mid")
                    log_result(SUCCESS_LOG, mid, safe_title, "SUCCESS")
                    done_ids.add(mid)

                except Exception as e:
                    print(f"  [{idx}/{len(page_ids)}] [失败] ID:{mid} -> 原因: {e}")
                    log_result(FAIL_LOG, mid, "UNKNOWN", str(e))

                time.sleep(random.uniform(1.2, 2.5))

            # 每达到设定页数，自动保存并推送到 Git 仓库
            if current_page % PUSH_INTERVAL == 0:
                git_commit_and_push(current_page)

            time.sleep(2)

        # 抓取结束后执行最终提交保存
        git_commit_and_push(MAX_PAGE, is_final=True)
        browser.close()
        print("\n[*] 全部抓取任务执行完毕！")

if __name__ == "__main__":
    main()