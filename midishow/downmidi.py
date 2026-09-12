import os
import re
import sys
import time
import random
import subprocess
from playwright.sync_api import sync_playwright
try:
    from playwright_stealth import stealth_sync
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False
    print("[!] playwright-stealth 未安装，将使用基础指纹抹除（pip install playwright-stealth）")

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
# DEFAULT_COOKIE_STR = "PHPSESSID=et8mol59odq7tj6f7k04oukepp; _csrf=35368ea1bd944a2594f915aa83947bf96babc6ba9bd55f09c586df4ecc4966d0a%3A2%3A%7Bi%3A0%3Bs%3A5%3A%22_csrf%22%3Bi%3A1%3Bs%3A32%3A%22Z1D9rdpnzbXqeefx0Z1Gun2zyrMtI2jD%22%3B%7D; _language=4be5658c4b69d6d6d0f856ff1d2abd82d33f89ab530702899ed361532fae4a24a%3A2%3A%7Bi%3A0%3Bs%3A9%3A%22_language%22%3Bi%3A1%3Bs%3A2%3A%22zh%22%3B%7D"
# pyrefly: ignore [parse-error]
DEFAULT_COOKIE_STR = "_gid=GA1.2.910328204.1789212463; _language=4be5658c4b69d6d6d0f856ff1d2abd82d33f89ab530702899ed361532fae4a24a%3A2%3A%7Bi%3A0%3Bs%3A9%3A%22_language%22%3Bi%3A1%3Bs%3A2%3A%22zh%22%3B%7D; _gat_gtag_UA_21955665_1=1; cf_clearance=OMKAT..NXJ6g8.1t4FB64jdkj5MwZU4Vwj68GxTCEjI-1789225653-1.2.1.1-XzKnA0vagwb_y4RTna.jH.iRDbXPbI1pITDPSz.oDakHY_DA04WAKL3HZTxLWEPX6W2g9e5FumQ4RkelG9OIhoxqO3GMXzTVPLaGisaoKiJ1UGsjyMWEyzhlxAw.9y7fFWtL4ZZf80XR6h1xL3DIIHrYZWe6FZEKlu3PCv76ZAaP15jY8BNBNwxgUvA5rtg1VgV5OA4eAhkyP9a8lfufzKtf3zhEck6c7H4ShegkLKzTRJ4M0OGh1y9tyLevsbUdt7H6YqfMj_R2Kn2zLMvy4A1eSvaUWLsTHTjaX1bUqz47v0gCxd8EAZuYaqVnzghMjSZ3jV_ZIAkux9kgk6rsz5g9s4GrI7oCvibVShKhHC636gUX6jDh21qC7xsuX1imR1WRldNYEIB8EmFbTAH9FKcms7t2XAVYNamrojWA28YSeC3uECWUu7ZVbBQynKnh; PHPSESSID=141t2ebmetg0bjs5sh56905ubt; _identity=a4cf7fd23fd10e83346ff5625ee42525f9ab82b4894d5a064f5058786b58df10a%3A2%3A%7Bi%3A0%3Bs%3A9%3A%22_identity%22%3Bi%3A1%3Bs%3A52%3A%22%5B1407975%2C%22ZpjeG5x27rfBMvswkcSDXAtQYV8zXtpm%22%2C2592000%5D%22%3B%7D; _csrf=b9d51c0a04d4ce4aba4aa1e272c477d3c9f213af9e10d6f517023262b6e937cda%3A2%3A%7Bi%3A0%3Bs%3A5%3A%22_csrf%22%3Bi%3A1%3Bs%3A32%3A%22IsxJ370ZMIqDRzcP_fCZ5NxtTEp4JZq3%22%3B%7D; _ga_BTCGHXH3SZ=GS2.1.s1789224655$o4$g1$t1789225673$j40$l0$h0; _ga=GA1.2.504136511.1789212463
COOKIE_STR = os.environ.get("MIDISHOW_COOKIE") or DEFAULT_COOKIE_STR

# 抹除自动化浏览器特征指纹（兜底，playwright-stealth 会做更全面的处理）
STEALTH_SCRIPT = """
// 基础 webdriver 指纹抹除
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// 伪造 chrome 对象
window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };

// 伪造插件列表（让浏览器看起来有真实插件）
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// 修正 languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
});

// 隐藏 Permissions 查询的自动化特征
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);
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

def _is_cf_challenge(page):
    """判断当前页面是否仍在 Cloudflare 验证中"""
    try:
        title = page.title().lower()
        if "just a moment" in title:
            return True
    except Exception:
        pass
    try:
        body_text = page.evaluate(
            "() => document.body ? document.body.innerText.slice(0, 500).toLowerCase() : ''"
        )
        if any(kw in body_text for kw in [
            "checking your browser", "cf-wrapper", "ray id",
            "enable javascript", "please wait", "security check"
        ]):
            return True
    except Exception:
        pass
    try:
        cur_url = page.url.lower()
        if "challenges.cloudflare.com" in cur_url:
            return True
    except Exception:
        pass
    return False


def _try_click_turnstile(page):
    """尝试找到并点击 Turnstile 验证框，返回是否成功点击"""
    # 方法1：遍历所有 frame，找到 CF challenge iframe
    for frame in page.frames:
        try:
            furl = frame.url
        except Exception:
            continue
        if "challenges.cloudflare.com" not in furl and "turnstile" not in furl:
            continue
        try:
            # 选择器优先级：checkbox > label > stage > 任何可见 input
            selectors = [
                'input[type="checkbox"]',
                '.ctp-checkbox-label',
                '#challenge-stage',
                '[id*="challenge"]',
                'label',
            ]
            for sel in selectors:
                cb = frame.locator(sel).first
                try:
                    if cb.count() > 0 and cb.is_visible():
                        box = cb.bounding_box()
                        if box and box['width'] > 0:
                            cx = box['x'] + box['width'] / 2
                            cy = box['y'] + box['height'] / 2
                            print(f"  [CF] 找到 Turnstile 元素 '{sel}'，坐标 ({int(cx)}, {int(cy)})，模拟人类点击...")
                            # 人类化鼠标移动：先移到附近再精确点击
                            page.mouse.move(cx - random.randint(20, 50), cy + random.randint(-10, 10))
                            time.sleep(random.uniform(0.2, 0.5))
                            page.mouse.move(cx, cy)
                            time.sleep(random.uniform(0.1, 0.3))
                            page.mouse.click(cx, cy)
                            return True
                except Exception:
                    continue
        except Exception:
            continue

    # 方法2：通过 JS 直接在所有 iframe 里触发点击（暗模式兜底）
    try:
        clicked_js = page.evaluate("""
            () => {
                const frames = document.querySelectorAll('iframe');
                for (const frame of frames) {
                    try {
                        const doc = frame.contentDocument || frame.contentWindow.document;
                        const cb = doc.querySelector('input[type=checkbox], .ctp-checkbox-label, #challenge-stage');
                        if (cb) { cb.click(); return true; }
                    } catch(e) {}
                }
                return false;
            }
        """)
        if clicked_js:
            print("  [CF] JS 跨 iframe 触发点击成功")
            return True
    except Exception:
        pass

    return False


def handle_cf_challenge(page, max_retries=3, wait_per_attempt=12):
    """检测并穿透 Cloudflare 验证挑战页
    
    策略：多特征识别 → 找 Turnstile iframe 模拟人类点击 → 循环等待页面变化
    """
    for attempt in range(max_retries):
        if not _is_cf_challenge(page):
            return True

        print(f"  [CF] 检测到 Cloudflare 验证挑战 (第 {attempt + 1}/{max_retries} 次)，尝试自动穿透...")

        # 等待 Turnstile iframe 加载完成（最多 5s）
        time.sleep(2)
        for _ in range(5):
            if any("challenges.cloudflare.com" in (f.url or "") or "turnstile" in (f.url or "")
                   for f in page.frames):
                break
            time.sleep(1)

        # 尝试点击 Turnstile
        clicked = _try_click_turnstile(page)
        if clicked:
            print(f"  [CF] 已点击验证框，等待页面自动跳转（最多 {wait_per_attempt}s）...")
        else:
            print("  [CF] 未找到可点击的 Turnstile 元素，等待 CF 自动验证...")

        # 循环检测页面是否离开了 CF 挑战页
        deadline = time.time() + wait_per_attempt
        while time.time() < deadline:
            time.sleep(1.5)
            if not _is_cf_challenge(page):
                print("  [CF] ✓ 成功穿透 Cloudflare 验证！")
                return True

        print(f"  [CF] 第 {attempt + 1} 次穿透尝试超时，继续下一次...")
        # 随机延迟，避免被识别为机器人
        time.sleep(random.uniform(2, 4))

    # 最终判断
    if not _is_cf_challenge(page):
        print("  [CF] ✓ 已通过 Cloudflare 验证！")
        return True
    print("  [CF] ✗ 所有穿透尝试均失败，页面可能仍被拦截。")
    return False

def _apply_stealth(page):
    """对页面应用所有反指纹措施"""
    page.add_init_script(STEALTH_SCRIPT)
    page.add_init_script(HOOK_SCRIPT)
    if HAS_STEALTH:
        try:
            stealth_sync(page)
        except Exception as e:
            pass  # stealth 失败不影响主流程


def create_browser_context(browser):
    """创建统一配置的浏览器上下文（包含视口、代理与 Cookie）"""
    context_kwargs = {
        "viewport": {'width': 1920, 'height': 1080},
        # 使用最新的真实 Chrome UA，避免被识别为旧版爬虫
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "color_scheme": "light",
        "java_script_enabled": True,
        # 模拟真实设备的额外 HTTP headers
        "extra_http_headers": {
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
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
            _apply_stealth(page)
    except Exception:
        context = create_browser_context(browser)
        page = context.new_page()
        _apply_stealth(page)
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
            "--no-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            "--flag-switches-begin",
            "--disable-site-isolation-trials",
            "--flag-switches-end",
            # 使用真实 Chrome channel 信号
            "--use-fake-device-for-media-stream",
        ]
    }
    if PROXY_SERVER:
        launch_kwargs["proxy"] = {"server": PROXY_SERVER}

    if HAS_STEALTH:
        print("[*] playwright-stealth 已加载，将深度抹除自动化指纹")
    else:
        print("[!] playwright-stealth 未安装，建议运行: pip install playwright-stealth")

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        context = create_browser_context(browser)
        page = context.new_page()
        _apply_stealth(page)

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