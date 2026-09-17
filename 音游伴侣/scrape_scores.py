#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
音游伴侣 (mgm.jie-you.cn) 乐谱自动化抓取与简谱量化归档脚本
支持虚拟显示器 (Xvfb) 运行、速率防检测控制、去重断点续传与全量/增量归档。
"""

import os
import sys
import time
import json
import re
import argparse
import urllib.parse
import builtins
import random
from datetime import datetime
from typing import Set, Dict, Any, List, Optional
from playwright.sync_api import sync_playwright, BrowserContext, Page

# 强制开启标准输出/错误无缓冲流式刷新，确保 GitHub Actions 控制台毫秒级实时打印日志
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True, write_through=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True, write_through=True)
except Exception:
    pass

_orig_print = builtins.print

def print(*args, **kwargs):
    # 强制每次打印自动 flush=True
    kwargs.setdefault("flush", True)
    _orig_print(*args, **kwargs)

builtins.print = print

# 路径基准：以当前仓库根目录为准
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "音游伴侣" else SCRIPT_DIR

DEFAULT_SAVE_DIR = os.path.join(REPO_ROOT, "音游伴侣", "scores")
DEFAULT_INDEX_FILE = os.path.join(REPO_ROOT, "音游伴侣", "downloaded_ids.json")
DEFAULT_AUTH_FILE = os.path.join(REPO_ROOT, "音游伴侣", "auth_state.json")

DEGREE_NAMES = ["1", "2", "3", "4", "5", "6", "7"]


def sanitize_filename(name: str) -> str:
    """过滤文件名中的非法字符"""
    clean = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip()
    return clean if clean else f"score_{int(time.time())}"


def key_to_jianpu_symbol(key_idx: int) -> str:
    """
    光遇 15 键转标准简谱唱名符号
    0~6   -> 1 2 3 4 5 6 7 (中音)
    7~13  -> 1' 2' 3' 4' 5' 6' 7' (高音)
    14    -> 1'' (倍高音)
    """
    if key_idx < 0 or key_idx > 14:
        return ""
    deg = DEGREE_NAMES[key_idx % 7]
    octave = key_idx // 7
    if octave == 0:
        return deg
    elif octave == 1:
        return f"{deg}'"
    else:
        return f"{deg}''"


def generate_jianpu_content(song_json: dict, score_id: int, fallback_title: str) -> str:
    """
    音游伴侣 16 槽位小节量化算法：复现网页端标准简谱
    """
    data = song_json.get("data", {}) if "data" in song_json else song_json
    score = data.get("score", {}) if "score" in data else data
    metadata = score.get("metadata", {})

    title = metadata.get("title") or score.get("title") or fallback_title
    artist = metadata.get("artist") or metadata.get("creator") or score.get("artist") or "佚名"
    bpm = score.get("bpm") or 120
    if bpm <= 0:
        bpm = 120

    # 提取音符序列 (智能过滤打击乐与静音声轨)
    tracks = score.get("tracks", [])
    raw_notes = []
    if tracks:
        has_solo = any(t.get("solo") for t in tracks)
        non_percussion_count = sum(1 for t in tracks if not any(p in str(t.get("name", "")).lower() or p in str(t.get("instrument", "")).lower() for p in ["drum", "tr_909", "tr-909", "sfx", "dun_dun", "percussion", "鼓", "打击乐", "音效", "排鼓", "手鼓"]))

        for t in tracks:
            if t.get("muted"):
                continue
            if has_solo and not t.get("solo"):
                continue
            tname = str(t.get("name", "")).lower()
            tinst = str(t.get("instrument", "")).lower()
            is_percussion = any(p in tname or p in tinst for p in ["drum", "tr_909", "tr-909", "sfx", "dun_dun", "percussion", "鼓", "打击乐", "音效", "排鼓", "手鼓"])
            if is_percussion and non_percussion_count > 0:
                continue
            raw_notes.extend(t.get("notes", []))
    else:
        raw_notes = score.get("notes", [])

    # 一拍毫秒 = 60000 / BPM; 16分音符槽位 = 一拍的 1/4
    slot_duration_ms = (60000.0 / bpm) / 4.0
    slot_map: Dict[int, Set[int]] = {}

    for n in raw_notes:
        # 获取起始时间
        t = n.get("startMs")
        if t is None:
            t = n.get("start_ms", n.get("time", n.get("timeMs", -1)))
        if t is None or t < 0:
            continue

        # 按键映射
        key_idx = -1
        raw_key = n.get("rawKey") or n.get("raw_key") or n.get("raw")
        if raw_key and isinstance(raw_key, str):
            # 1Key0 ~ 1Key14 (0-based)
            m = re.search(r"Key(\d+)", raw_key, re.IGNORECASE)
            if m:
                k = int(m.group(1))
                if 0 <= k <= 14:
                    key_idx = k
            # col:track 如 "5:1" (0-based col)
            m_col = re.search(r"^(\d+):(\d+)$", raw_key.strip())
            if m_col and key_idx == -1:
                k = int(m_col.group(1))
                if 0 <= k <= 14:
                    key_idx = k

        if key_idx == -1 and "targetKey" in n and n["targetKey"]:
            tk = str(n["targetKey"]).strip()
            m = re.search(r"key\.(\d+)", tk, re.IGNORECASE)
            if m:
                k = int(m.group(1)) - 1
                if 0 <= k <= 14:
                    key_idx = k
            elif tk.isdigit():
                k = int(tk) - 1
                if 0 <= k <= 14:
                    key_idx = k

        if key_idx == -1 and "keyIndex" in n and n["keyIndex"] is not None:
            try:
                k = int(n["keyIndex"]) - 1
                if 0 <= k <= 14:
                    key_idx = k
            except:
                pass

        if key_idx == -1 and raw_key and str(raw_key).strip().isdigit():
            k = int(str(raw_key).strip()) - 1
            if 0 <= k <= 14:
                key_idx = k

        if key_idx == -1 and "pitch" in n and n["pitch"] is not None:
            try:
                p = int(n["pitch"])
                if 1 <= p <= 15:
                    key_idx = p - 1
            except:
                pass

        if 0 <= key_idx <= 14:
            slot = round(t / slot_duration_ms)
            slot_map.setdefault(slot, set()).add(key_idx)

    max_slot = max(slot_map.keys()) if slot_map else 0
    total_bars = (max_slot // 16) + 1

    lines = []
    lines.append("=" * 60)
    lines.append("          光遇 15 键标准简谱 (音游伴侣网格量化引擎生成)")
    lines.append("=" * 60)
    lines.append(f"曲目名称: 《{title}》 (ID: {score_id})")
    lines.append(f"编曲作者: {artist}")
    lines.append(f"演奏速度: {bpm} BPM | 节拍: 4/4 拍 | 网格细分: 16分音符 ({slot_duration_ms:.1f}ms/槽)")
    lines.append(f"音符总数: {len(raw_notes)} 个")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("【琴键与简谱唱名对照】")
    lines.append("  第一排 (低/中音): A1(1)  A2(2)  A3(3)  A4(4)  A5(5)")
    lines.append("  第二排 (中/高音): B1(6)  B2(7)  B3(1') B4(2') B5(3')")
    lines.append("  第三排 (高/倍高): C1(4') C2(5') C3(6') C4(7') C5(1'')")
    lines.append("符号说明: '.' = 空拍/延音; 数字带点(') = 高音; [ ] = 和弦同时按压")
    lines.append("=" * 60)
    lines.append("")

    for bar in range(total_bars):
        bar_slots = []
        for s in range(16):
            cur_slot = bar * 16 + s
            keys = sorted(slot_map.get(cur_slot, []))
            if not keys:
                bar_slots.append(".")
            elif len(keys) == 1:
                bar_slots.append(key_to_jianpu_symbol(keys[0]))
            else:
                chord = "".join(key_to_jianpu_symbol(k) for k in keys)
                bar_slots.append(f"[{chord}]")

        b1 = " ".join(bar_slots[0:4])
        b2 = " ".join(bar_slots[4:8])
        b3 = " ".join(bar_slots[8:12])
        b4 = " ".join(bar_slots[12:16])
        lines.append(f"第 {bar + 1:02d} 小节:  {b1}  |  {b2}  |  {b3}  |  {b4}")

    lines.append("")
    lines.append("=" * 60)
    lines.append("                    简谱生成完毕，祝演奏愉快！")
    lines.append("=" * 60)
    return "\n".join(lines)


def load_downloaded_ids(index_file: str, save_dir: str) -> (Set[int], Dict[str, Any]):
    """加载已抓取的乐谱 ID 记录（包含文件扫描双重去重）"""
    downloaded_ids = set()
    index_data = {"last_updated": "", "total_downloaded": 0, "ids": [], "records": {}}

    if os.path.exists(index_file):
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                index_data = json.load(f)
                for sid in index_data.get("ids", []):
                    downloaded_ids.add(int(sid))
        except Exception as e:
            print(f"[!] 读取索引文件失败: {e}")

    # 同时扫描本地磁盘现有已保存文件
    scan_dirs = [save_dir, os.path.join(REPO_ROOT, "音游伴侣")]
    for sdir in scan_dirs:
        if os.path.exists(sdir):
            for fname in os.listdir(sdir):
                m = re.match(r"^(\d+)_.*\.json$", fname)
                if m:
                    downloaded_ids.add(int(m.group(1)))

    print(f"[*] 本地已存在乐谱记录数: {len(downloaded_ids)} 首")
    return downloaded_ids, index_data


def save_downloaded_index(index_file: str, index_data: dict, downloaded_ids: Set[int]):
    """持久化保存下载索引记录"""
    index_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    index_data["ids"] = sorted(list(downloaded_ids))
    index_data["total_downloaded"] = len(downloaded_ids)
    os.makedirs(os.path.dirname(index_file), exist_ok=True)
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)


def interact_score(context: BrowserContext, sid: int, title: str, common_headers: dict):
    """
    下载成功后 30% 概率触发点赞或收藏，模拟真实用户交互行为。
    下载成功 3 秒后执行，全链路异常保护，绝不抛出异常或阻塞主流程，日志实时输出到控制台。
    """
    try:
        if random.random() >= 0.20:
            return

        action_type = random.choice(["like", "favorite"])
        action_name = "点赞" if action_type == "like" else "收藏"

        print(f"  [🎲 互动触发] 命中 30% 交互概率，将在 3 秒后对 ID {sid} 执行【{action_name}】...")
        time.sleep(3)

        interact_url = f"https://mgm.jie-you.cn/web-api/business/scores/{sid}/{action_type}"
        resp = context.request.post(
            interact_url,
            headers={
                **common_headers,
                "origin": "https://mgm.jie-you.cn",
                "referer": f"https://mgm.jie-you.cn/scores/{sid}",
                "content-length": "0",
            },
            data="",
            timeout=10000,
        )

        if resp.status == 200:
            print(f"  [❤️ {action_name}成功] ID {sid} 《{title}》已成功【{action_name}】(HTTP 200)")
        elif resp.status == 429:
            print(f"  [⚠️ {action_name}限流] ID {sid} 执行【{action_name}】收到 HTTP 429，已跳过互动")
        else:
            print(f"  [⚠️ {action_name}返回] ID {sid} HTTP 状态码 {resp.status}，响应内容: {resp.text()[:100]}")
    except Exception as e:
        # 处理不抛出任何异常，确保主抓取流程绝对稳定
        print(f"  [⚠️ 互动异常] ID {sid} 执行点赞/收藏异常（已安全捕获忽略）: {e}")


def save_auth_state(context: BrowserContext, auth_file: str):
    """持久化保存当前登录会话票据 (Cookies 与 LocalStorage)"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(auth_file)), exist_ok=True)
        context.storage_state(path=auth_file)
        cookies = context.cookies()
        print(f"[+] 登录票据已成功保存至: {auth_file} (已持久化 {len(cookies)} 个 Cookie)")
    except Exception as e:
        print(f"[⚠️ 票据保存失败] {e}")


def is_auth_valid(context: BrowserContext, common_headers: dict) -> bool:
    """
    检查当前会话中的登录票据是否仍然有效。
    调用需鉴权的用户接口 (interaction-center/summary)，判断票据是否有效。
    """
    try:
        res = context.request.get(
            "https://mgm.jie-you.cn/web-api/user/interaction-center/summary",
            headers={
                **common_headers,
                "referer": "https://mgm.jie-you.cn/",
            },
            timeout=10000,
        )
        if res.status == 200:
            try:
                data = res.json()
                if isinstance(data, dict) and data.get("success") is True:
                    return True
            except Exception:
                return True
        elif res.status in (401, 403):
            return False
    except Exception as e:
        print(f"  [*] 校验登录票据网络异常: {e}")
    return False


def perform_login(context: BrowserContext, page: Optional[Page], username: str, password: str, common_headers: dict, auth_file: str) -> bool:
    """执行账号认证登录流程 (优先 API 极速登录，失败则使用浏览器前端表单兜底)，成功后保存票据"""
    print(f"[*] 正在执行音游伴侣账号认证 (账号: {username})...")
    login_success = False
    login_payload = {
        "username": username,
        "password": password,
        "device_name": "Web 浏览器",
        "platform": "web",
    }
    try:
        api_res = context.request.post(
            "https://mgm.jie-you.cn/web-api/user/auth/login",
            headers={
                **common_headers,
                "content-type": "application/json",
                "origin": "https://mgm.jie-you.cn",
                "referer": "https://mgm.jie-you.cn/login",
            },
            data=json.dumps(login_payload),
            timeout=15000,
        )
        print(f"[+] 登录接口响应状态码: {api_res.status}")
        if api_res.status == 200:
            print("[✓] 音游伴侣 API 认证成功！")
            login_success = True
    except Exception as e:
        print(f"[*] API 直连登录跳过: {e}")

    # 若 API 登录失败，尝试浏览器前端表单兜底登录
    if not login_success and page:
        print("[*] 尝试通过浏览器表单进行兜底登录: https://mgm.jie-you.cn/login ...")
        try:
            page.goto("https://mgm.jie-you.cn/login", wait_until="domcontentloaded", timeout=30000)
            user_input = page.wait_for_selector('input[type="text"], input[name="username"], input[placeholder*="账号"], input[placeholder*="用户名"]', timeout=6000)
            pass_input = page.wait_for_selector('input[type="password"], input[name="password"], input[placeholder*="密码"]', timeout=6000)
            if user_input and pass_input:
                user_input.fill(username)
                pass_input.fill(password)
                page.wait_for_timeout(500)
                login_btn = page.query_selector('button[type="submit"], button:has-text("登录")')
                if login_btn:
                    login_btn.click()
                    page.wait_for_timeout(3000)
                    print("[+] 已提交前端登录表单")
                    if is_auth_valid(context, common_headers):
                        login_success = True
        except Exception as e:
            print(f"[!] 兜底登录异常: {e}")

    if login_success:
        save_auth_state(context, auth_file)
    else:
        print("[⚠️ 登录警告] 账号认证未确认成功，将尝试以现有会话继续...")

    return login_success


def main():
    parser = argparse.ArgumentParser(description="音游伴侣全量乐谱自动抓取与简谱生成归档器")
    parser.add_argument("--max-count", type=int, default=int(os.environ.get("MAX_COUNT", 100)), help="本次抓取最大数量 (默认 100)")
    rate_hour_env = os.environ.get("RATE_PER_HOUR")
    if rate_hour_env is not None:
        default_rate_hour = int(rate_hour_env)
    elif "RATE_PER_MINUTE" in os.environ:
        default_rate_hour = max(1, int(os.environ["RATE_PER_MINUTE"]) * 60)
    else:
        default_rate_hour = 10

    parser.add_argument("--rate-per-hour", type=int, default=default_rate_hour, help="每小时抓取速率 (默认 10 个/小时)")
    parser.add_argument("--rate-per-minute", type=int, default=None, help="每分钟抓取速率 (兼容旧参数)")
    parser.add_argument("--username", type=str, default=os.environ.get("MGM_USERNAME", "lollol"), help="音游伴侣登录账号")
    parser.add_argument("--password", type=str, default=os.environ.get("MGM_PASSWORD", "123456"), help="音游伴侣登录密码")
    parser.add_argument("--start-page", type=int, default=int(os.environ.get("START_PAGE", 1)), help="起始页码 (默认 1)")
    parser.add_argument("--save-dir", type=str, default=os.environ.get("SAVE_DIR", DEFAULT_SAVE_DIR), help="乐谱与简谱保存目录")
    parser.add_argument("--auth-file", type=str, default=os.environ.get("AUTH_FILE", DEFAULT_AUTH_FILE), help="登录票据存储路径 (默认 音游伴侣/auth_state.json)")
    parser.add_argument("--headless", type=str, default=os.environ.get("HEADLESS", "false"), help="是否以无头模式运行 (使用 Xvfb 时应为 false)")
    args = parser.parse_args()

    max_count = args.max_count
    if args.rate_per_minute is not None:
        rate_per_hour = max(1, args.rate_per_minute * 60)
    else:
        rate_per_hour = max(1, args.rate_per_hour)
    delay_between_scores = 3600.0 / rate_per_hour
    username = args.username.strip()
    password = args.password.strip()
    start_page = max(1, args.start_page)
    save_dir = os.path.abspath(args.save_dir)
    auth_file = os.path.abspath(args.auth_file)
    is_headless = args.headless.lower() == "true"

    os.makedirs(save_dir, exist_ok=True)
    index_file = DEFAULT_INDEX_FILE

    print("=" * 60)
    print("      音游伴侣 (mgm.jie-you.cn) 乐谱自动化采集系统")
    print("=" * 60)
    print(f"🎯 抓取目标上限: {max_count} 首")
    print(f"⏱️ 速率限制: {rate_per_hour} 个/小时 (单次间隔约 {delay_between_scores:.1f} 秒)")
    print(f"📄 起始页码: 第 {start_page} 页 (按播放量最多排序 sort=plays)")
    print(f"👤 登录账号: {username}")
    print(f"🔑 票据文件: {auth_file}")
    print(f"📁 保存目录: {save_dir}")
    print("=" * 60)

    downloaded_ids, index_data = load_downloaded_ids(index_file, save_dir)

    with sync_playwright() as p:
        print("[*] 正在启动 Chromium 浏览器环境 (虚拟显示器渲染)...")
        browser = p.chromium.launch(
            headless=is_headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1920,1080",
            ],
        )

        # 根据 req.txt 完全复刻 Chrome 152 真实浏览器请求标头
        common_headers = {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "priority": "u=1, i",
            "sec-ch-ua": '"Chromium";v="152", "Not?A_Brand";v="24", "Google Chrome";v="152"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        }

        # 准备 BrowserContext 启动配置 (若本地存在历史票据则自动装载会话)
        context_kwargs = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": common_headers["user-agent"],
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "extra_http_headers": {
                "accept-language": common_headers["accept-language"],
                "sec-ch-ua": common_headers["sec-ch-ua"],
                "sec-ch-ua-mobile": common_headers["sec-ch-ua-mobile"],
                "sec-ch-ua-platform": common_headers["sec-ch-ua-platform"],
            },
        }

        has_local_auth = False
        if os.path.exists(auth_file) and os.path.getsize(auth_file) > 10:
            try:
                with open(auth_file, "r", encoding="utf-8") as f:
                    auth_data = json.load(f)
                    if isinstance(auth_data, dict) and (auth_data.get("cookies") or auth_data.get("origins")):
                        context_kwargs["storage_state"] = auth_file
                        has_local_auth = True
                        print(f"[*] 发现本地已保存登录票据: {auth_file}，已预先装入浏览器会话")
            except Exception as e:
                print(f"[*] 读取本地票据异常 ({e})，将重新登录")

        context: BrowserContext = browser.new_context(**context_kwargs)
        page: Page = context.new_page()

        # 拦截无用的媒体、图片与字体请求，节省网络带宽与请求量
        try:
            page.route(
                "**/*",
                lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_(),
            )
        except Exception:
            pass

        # 1. 登录会话校验与执行 (若本地票据有效则直接跳过登录；若失效或无票据才执行登录)
        need_login = True
        if has_local_auth:
            print("[*] 正在校验本地登录票据有效性...")
            if is_auth_valid(context, common_headers):
                print("[✓] 本地登录票据依然有效，无需重复登录（模拟真实长期在线用户）！")
                need_login = False
            else:
                print("[*] 本地登录票据已失效或过期，准备重新登录获取新票据...")

        if need_login:
            perform_login(context, page, username, password, common_headers, auth_file)

        # 2. 遍历播放最多列表页面 (sort=plays)
        current_page = start_page
        scraped_this_run = 0
        is_rate_limited = False

        # 用于浏览器兜底时的网络响应拦截
        captured_scores: List[dict] = []

        def on_response(resp):
            if "web-api/business/scores" in resp.url and resp.status == 200:
                try:
                    res_json = resp.json()
                    items = res_json.get("data", {}).get("items", [])
                    if items:
                        captured_scores.extend(items)
                except Exception:
                    pass

        page.on("response", on_response)

        while scraped_this_run < max_count and not is_rate_limited:
            page_url = f"https://mgm.jie-you.cn/scores?sort=plays&page={current_page}"
            api_url = f"https://mgm.jie-you.cn/web-api/business/scores?sort=plays&page={current_page}"
            print(f"\n[{current_page}] 正在获取乐谱列表 (对应页面: {page_url}) ...")

            page_cards: List[dict] = []

            # 方案 B: 直接请求列表 API (每页仅 1 次轻量 JSON 请求，零图片/CSS/JS开销)
            try:
                api_res = context.request.get(
                    api_url,
                    headers={
                        **common_headers,
                        "referer": page_url,
                    },
                    timeout=20000,
                )
                if api_res.status == 200:
                    res_json = api_res.json()
                    items = res_json.get("data", {}).get("items", [])
                    for item in items:
                        sid = item.get("id")
                        title = item.get("title") or f"Score_{sid}"
                        if sid:
                            page_cards.append({
                                "id": int(sid),
                                "title": title,
                                "bpm": item.get("bpm", 120),
                                "artist": item.get("creator") or item.get("artist") or "佚名",
                            })
                elif api_res.status == 429:
                    print(f"[🚫 触发限流 429] 列表接口返回 HTTP 429 (Too Many Requests)！平台频率受限，立即终止抓取。")
                    is_rate_limited = True
                    break
                else:
                    print(f"[!] 列表接口返回状态码 {api_res.status}，尝试浏览器兜底加载...")
            except Exception as e:
                print(f"[!] 列表接口请求异常: {e}，尝试浏览器兜底加载...")

            # 浏览器兜底：仅当 API 直连未解析到卡片且未触发限流时才启动浏览器渲染
            if not page_cards and not is_rate_limited:
                print(f"[*] 正在通过浏览器访问页面: {page_url} ...")
                captured_scores.clear()
                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(2000)
                except Exception as e:
                    print(f"[!] 页面加载超时或错误: {e}")

                if captured_scores:
                    for item in captured_scores:
                        sid = item.get("id")
                        title = item.get("title") or f"Score_{sid}"
                        if sid and not any(c["id"] == int(sid) for c in page_cards):
                            page_cards.append({
                                "id": int(sid),
                                "title": title,
                                "bpm": item.get("bpm", 120),
                                "artist": item.get("creator") or item.get("artist") or "佚名",
                            })

                dom_links = page.query_selector_all('a[href*="/scores/"]')
                for a in dom_links:
                    href = a.get_attribute("href") or ""
                    m = re.search(r"/scores/(\d+)(?:-([^\s\"'>?]+))?", href)
                    if m:
                        sid = int(m.group(1))
                        if not any(c["id"] == sid for c in page_cards):
                            raw_title = m.group(2)
                            title_text = urllib.parse.unquote(raw_title) if raw_title else (a.inner_text().strip() or f"Score_{sid}")
                            page_cards.append({
                                "id": sid,
                                "title": title_text,
                                "bpm": 120,
                                "artist": "佚名",
                            })

            if not page_cards:
                print(f"[!] 第 {current_page} 页未检测到任何乐谱卡片，已到底或被限流，结束抓取。")
                break

            print(f"[*] 第 {current_page} 页共解析到 {len(page_cards)} 个乐谱卡片")

            for card in page_cards:
                if scraped_this_run >= max_count:
                    break

                sid = card["id"]
                title = card["title"]

                # 判定是否已保存
                if sid in downloaded_ids:
                    print(f"  [⏭️ 跳过] ID {sid} 《{title}》 本地已有记录")
                    continue

                safe_title = sanitize_filename(title)
                json_filename = f"{sid}_{safe_title}.json"
                txt_filename = f"{sid}_{safe_title}_简谱.txt"
                json_path = os.path.join(save_dir, json_filename)
                txt_path = os.path.join(save_dir, txt_filename)

                # 下载乐谱全量 JSON
                download_url = f"https://mgm.jie-you.cn/web-api/business/scores/{sid}/file?variant=full"
                print(f"  [⬇️ 下载] 正在下载 ({scraped_this_run + 1}/{max_count}) ID {sid} 《{title}》...")

                try:
                    file_resp = context.request.get(
                        download_url,
                        headers={
                            **common_headers,
                            "referer": f"https://mgm.jie-you.cn/scores/{sid}",
                        },
                        timeout=20000,
                    )

                    # 如果遇到 401 票据过期，重新登录并重试一次下载
                    if file_resp.status == 401:
                        print(f"  [⚠️ 票据失效 401] 下载 ID {sid} 遇到 401 未授权，正在重新登录刷新票据...")
                        if perform_login(context, page, username, password, common_headers, auth_file):
                            file_resp = context.request.get(
                                download_url,
                                headers={
                                    **common_headers,
                                    "referer": f"https://mgm.jie-you.cn/scores/{sid}",
                                },
                                timeout=20000,
                            )

                    if file_resp.status == 429:
                        print(f"  [🚫 触发限流 429] 下载 ID {sid} 时收到 HTTP 429 (Too Many Requests)！平台频率受限，立即终止抓取退出。")
                        is_rate_limited = True
                        break

                    if file_resp.status != 200:
                        print(f"  [⚠️ 跳过] 下载失败: ID {sid} HTTP 状态码 {file_resp.status}")
                        continue

                    raw_json_text = file_resp.text()
                    if not raw_json_text or len(raw_json_text) < 20:
                        print(f"  [⚠️ 跳过] 下载内容为空: ID {sid}")
                        continue

                    # 验证 JSON
                    song_data = json.loads(raw_json_text)

                    # 1. 保存原始 JSON
                    with open(json_path, "w", encoding="utf-8") as f:
                        f.write(raw_json_text)

                    # 2. 生成标准 16 槽位网格简谱并保存
                    jianpu_text = generate_jianpu_content(song_data, sid, title)
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(jianpu_text)

                    # 3. 记录已下载 ID 与元数据
                    downloaded_ids.add(sid)
                    index_data.setdefault("records", {})[str(sid)] = {
                        "title": title,
                        "json_file": json_filename,
                        "txt_file": txt_filename,
                        "download_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    save_downloaded_index(index_file, index_data, downloaded_ids)

                    scraped_this_run += 1
                    print(f"  [✅ 成功] ({scraped_this_run}/{max_count}) 已归档: {json_filename} 及简谱")

                    # 下载成功后 30% 概率触发点赞或收藏互动 (延迟3秒执行，全异常捕获)
                    interact_score(context, sid, title, common_headers)

                    # 速率控制 (防封/防风控)
                    if scraped_this_run < max_count:
                        print(f"  [⏳ 休眠] 速率控制 ({rate_per_hour}个/小时)，等待 {delay_between_scores:.1f} 秒...")
                        time.sleep(delay_between_scores)

                except Exception as e:
                    print(f"  [⚠️ 异常跳过] 处理 ID {sid} 出错: {e}")
                    time.sleep(delay_between_scores)
                    continue

            if is_rate_limited:
                break

            current_page += 1

        print("\n" + "=" * 60)
        if is_rate_limited:
            print("🛑 任务因触发服务端 HTTP 429 限流保护而提前终止，防封禁策略已生效。")
        else:
            print("🎉 本次任务执行完毕！")
        print(f"✅ 成功新抓取归档: {scraped_this_run} 首")
        print(f"📚 本地乐谱库总计: {len(downloaded_ids)} 首")
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    main()
