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
from datetime import datetime
from typing import Set, Dict, Any, List, Optional
from playwright.sync_api import sync_playwright, BrowserContext, Page

# 路径基准：以当前仓库根目录为准
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "音游伴侣" else SCRIPT_DIR

DEFAULT_SAVE_DIR = os.path.join(REPO_ROOT, "音游伴侣", "scores")
DEFAULT_INDEX_FILE = os.path.join(REPO_ROOT, "音游伴侣", "downloaded_ids.json")

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

    # 提取音符序列
    tracks = score.get("tracks", [])
    raw_notes = []
    if tracks:
        for t in tracks:
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

        # 按键映射：优先取 0-based rawKey ("1Key3" -> 3)
        key_idx = -1
        raw_key = n.get("rawKey") or n.get("raw_key")
        if raw_key and "Key" in str(raw_key):
            m = re.search(r"Key(\d+)", str(raw_key), re.IGNORECASE)
            if m:
                key_idx = int(m.group(1))
        elif "targetKey" in n and n["targetKey"]:
            m = re.search(r"key\.(\d+)", str(n["targetKey"]), re.IGNORECASE)
            if m:
                key_idx = int(m.group(1)) - 1
        elif "keyIndex" in n and n["keyIndex"] is not None:
            key_idx = int(n["keyIndex"]) - 1

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


def main():
    parser = argparse.ArgumentParser(description="音游伴侣全量乐谱自动抓取与简谱生成归档器")
    parser.add_argument("--max-count", type=int, default=int(os.environ.get("MAX_COUNT", 100)), help="本次抓取最大数量 (默认 100)")
    parser.add_argument("--rate-per-minute", type=int, default=int(os.environ.get("RATE_PER_MINUTE", 5)), help="每分钟抓取速率 (默认 5 个/分)")
    parser.add_argument("--username", type=str, default=os.environ.get("MGM_USERNAME", "lollol"), help="音游伴侣登录账号")
    parser.add_argument("--password", type=str, default=os.environ.get("MGM_PASSWORD", "123456"), help="音游伴侣登录密码")
    parser.add_argument("--start-page", type=int, default=int(os.environ.get("START_PAGE", 1)), help="起始页码 (默认 1)")
    parser.add_argument("--save-dir", type=str, default=os.environ.get("SAVE_DIR", DEFAULT_SAVE_DIR), help="乐谱与简谱保存目录")
    parser.add_argument("--headless", type=str, default=os.environ.get("HEADLESS", "false"), help="是否以无头模式运行 (使用 Xvfb 时应为 false)")
    args = parser.parse_args()

    max_count = args.max_count
    rate_per_minute = max(1, args.rate_per_minute)
    delay_between_scores = 60.0 / rate_per_minute
    username = args.username.strip()
    password = args.password.strip()
    start_page = max(1, args.start_page)
    save_dir = os.path.abspath(args.save_dir)
    is_headless = args.headless.lower() == "true"

    os.makedirs(save_dir, exist_ok=True)
    index_file = DEFAULT_INDEX_FILE

    print("=" * 60)
    print("      音游伴侣 (mgm.jie-you.cn) 乐谱自动化采集系统")
    print("=" * 60)
    print(f"🎯 抓取目标上限: {max_count} 首")
    print(f"⏱️ 速率限制: {rate_per_minute} 个/分钟 (单次间隔约 {delay_between_scores:.1f} 秒)")
    print(f"📄 起始页码: 第 {start_page} 页 (按播放量最多排序 sort=plays)")
    print(f"👤 登录账号: {username}")
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

        context: BrowserContext = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        )

        page: Page = context.new_page()

        # 1. 登录流程
        print("[*] 正在进入登录页面: https://mgm.jie-you.cn/login ...")
        try:
            page.goto("https://mgm.jie-you.cn/login", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)

            # 优先通过前端页面表单进行交互式登录
            try:
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
            except Exception as e:
                print(f"[*] 前端表单填报跳过: {e}，将采用 API 直连登录...")

            # 兜底：直接向登录 API 发送 POST 请求绑定 Session Cookie
            login_payload = {
                "username": username,
                "password": password,
                "device_name": "Web 浏览器",
                "platform": "web",
            }
            api_res = context.request.post(
                "https://mgm.jie-you.cn/web-api/user/auth/login",
                headers={
                    "Content-Type": "application/json",
                    "Referer": "https://mgm.jie-you.cn/login",
                    "Origin": "https://mgm.jie-you.cn",
                },
                data=json.dumps(login_payload),
            )
            print(f"[+] 登录接口响应状态码: {api_res.status}")
            if api_res.status == 200:
                print("[✓] 音游伴侣账号认证成功！")
            else:
                print(f"[!] 登录接口警告: 返回码 {api_res.status}，继续尝试进入曲库...")

        except Exception as e:
            print(f"[!] 登录过程出现异常: {e}，尝试继续进入播放最多大厅...")

        # 2. 遍历播放最多列表页面 (sort=plays)
        current_page = start_page
        scraped_this_run = 0

        # 用于存储页面捕获到的接口卡片数据
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

        while scraped_this_run < max_count:
            target_url = f"https://mgm.jie-you.cn/scores?sort=plays&page={current_page}"
            print(f"\n[{current_page}] 正在访问: {target_url} ...")
            captured_scores.clear()

            try:
                page.goto(target_url, wait_until="networkidle", timeout=35000)
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"[!] 页面加载超时或错误: {e}")

            # 聚合卡片信息：优先从网络响应拦截，兜底从 DOM 提取
            page_cards: List[dict] = []

            # 方式 A: 来自 API 拦截到的结构化数据
            if captured_scores:
                for item in captured_scores:
                    sid = item.get("id")
                    title = item.get("title") or f"Score_{sid}"
                    if sid:
                        page_cards.append({
                            "id": int(sid),
                            "title": title,
                            "bpm": item.get("bpm", 120),
                            "artist": item.get("creator") or item.get("artist") or "佚名",
                        })

            # 方式 B: DOM 解析兜底
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
                            "Referer": f"https://mgm.jie-you.cn/scores/{sid}",
                            "Accept": "*/*",
                        },
                        timeout=20000,
                    )

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

                    # 速率控制 (防封/防风控)
                    if scraped_this_run < max_count:
                        print(f"  [⏳ 休眠] 速率控制 ({rate_per_minute}个/分)，等待 {delay_between_scores:.1f} 秒...")
                        time.sleep(delay_between_scores)

                except Exception as e:
                    print(f"  [⚠️ 异常跳过] 处理 ID {sid} 出错: {e}")
                    continue

            current_page += 1

        print("\n" + "=" * 60)
        print(f"🎉 本次任务执行完毕！成功新抓取归档: {scraped_this_run} 首")
        print(f"📚 本地乐谱库总计: {len(downloaded_ids)} 首")
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    main()
