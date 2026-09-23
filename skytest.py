import base64
import hashlib
import json
import os
import random
import time
import uuid
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import requests

# ==================== 1. 账号与游戏配置参数 ====================
# 从抓包中提取的身份凭证（Token 失效时需替换为最新抓包值）
GL_TOKEN = "e32c06d7e47146b79a6577dd4a0650a8"
GL_UID = "84a19701a7284bfdbccf10f9feaad6df"
GL_DEVICEID = "2d7ae29fdd394393a64c9538b2b83524"

# 目标小游戏 ID（叠叠乐）与目标上报数值
MINI_GAME_ID = "6a99380e8e707f333dfd3d74"
DEFAULT_SCORE = 5593.0     # 默认初始总分（首次运行且无json时使用）
DEFAULT_PLAY_TIME = 3052.0 # 默认初始累计时长（秒）

# 数据存储 JSON 路径（与本脚本同级目录）
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_data.json")

# 逆向提取出的固定加密主盐
CRYPTO_KEY_SALT = b"d8f3a91c6e4b2f7a0c5d3e8f1a6b9c2d"

# 客户端行为埋点日志（sigma-buriedpoint）配置
ENABLE_BURIED_POINT_LOG = True  # 每次上报分数前是否自动模拟发送行为埋点日志
LOG_SESSION_CID = "938060579.1789542746"
LOG_CD95 = "5cb546a0d5456870b97d9424"
LOG_CD96 = "249ad307-05cf-4d84-9339-1b5dc09ee414"
LOG_COUNT_PER_ROUND = 3         # 每次上报前模拟发送的连续层数日志数（默认模拟最后3层）

# ==================== 本地数据 JSON 持久化 ====================
def load_game_data() -> tuple[int, int, int]:
    """读取本地 JSON 存储的数据，若不存在则创建并返回默认值"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                score = int(round(float(data.get("score", DEFAULT_SCORE))))
                play_time = int(round(float(data.get("play_time", DEFAULT_PLAY_TIME))))
                log_seq = int(data.get("log_seq", 305))
                return score, play_time, log_seq
        except Exception as e:
            print(f"[!] 读取本地 {DATA_FILE} 失败，使用默认值: {e}")
    # 首次若文件不存在则初始化保存默认值
    save_game_data(int(DEFAULT_SCORE), int(DEFAULT_PLAY_TIME), 305)
    return int(DEFAULT_SCORE), int(DEFAULT_PLAY_TIME), 305

def save_game_data(score: int, play_time: int, log_seq: int = 305):
    """保存最新数据到本地 JSON 文件"""
    data = {
        "score": int(score),
        "play_time": int(play_time),
        "log_seq": int(log_seq),
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[+] 数据已成功保存至本地 JSON: {DATA_FILE}")
    except Exception as e:
        print(f"[-] 写入数据文件失败: {e}")

# ==================== 2. 加密逻辑实现 ====================
def encrypt_game_data(payload_dict: dict, ts: int) -> str:
    """
    还原 mini-game-data-sdk 的 cl() 加密函数:
    1. 生成随机 16 字节 IV
    2. 基于 Math.floor(ts / 30000) 派生 256 位 PBKDF2-SHA256 密钥
    3. AES-256-CBC 加密并与 IV 拼接为 Base64
    """
    # 紧凑序列化 JSON（去除空格以保证格式与前端一致）
    raw_text = json.dumps(payload_dict, separators=(',', ':'), ensure_ascii=False)
    
    # 派生密钥：Salt 为 ts // 30000 的字符串字节
    dynamic_salt = str(ts // 30000).encode("utf-8")
    aes_key = hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=CRYPTO_KEY_SALT,
        salt=dynamic_salt,
        iterations=1000,
        dklen=32
    )

    # 生成 16 字节随机 IV
    iv = os.urandom(16)
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    
    # PKCS7 填充并加密
    padded_data = pad(raw_text.encode("utf-8"), AES.block_size)
    ciphertext = cipher.encrypt(padded_data)
    
    # 前端规范：IV(16 bytes) + Ciphertext，然后进行 Base64 编码
    combined = iv + ciphertext
    return base64.b64encode(combined).decode("utf-8")

# ==================== 3. 构造请求与发送 ====================
def send_game_logs(delta_score: int, log_seq: int) -> int:
    """
    在每次提交总分前，模拟发送客户端连续放置积木的行为日志 (sigma-buriedpoint 打点)
    - 严格按本次【增加的分数 delta_score】计算当前局游戏的最终得分与叠层数
    - 游戏真实机制: layers = score + 1，当局最终结算分即为 delta_score
    - 每轮分配独立的 round_uuid (cd97)
    - _s 序号自增推进并持久化保存
    """
    url = "https://sigma-buriedpoint-a19.proxima.nie.netease.com/log"
    log_headers = {
        "Host": "sigma-buriedpoint-a19.proxima.nie.netease.com",
        "user-agent": "Mozilla/5.0 (Linux; Android 13; 23054RA19C Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/111.0.5563.116 Mobile Safari/537.36 Godlike/4.24.0 (channel/wyds_dl_homeholdh5) UEPay/com.netease.gl/android7.13.5",
        "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "x-requested-with": "com.netease.gl",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "no-cors",
        "sec-fetch-dest": "image",
        "referer": "https://wp.ds.163.com/",
        "accept-encoding": "gzip, deflate, br",
        "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    target_score = max(1, int(delta_score))
    count = min(LOG_COUNT_PER_ROUND, target_score)
    start_s = max(1, target_score - count + 1)
    round_uuid = str(uuid.uuid4())

    for s in range(start_s, target_score + 1):
        now_time = time.strftime("%Y-%m-%d %H:%M:%S")
        el_payload = {
            "open_from": "",
            "game": "ma75",
            "scene": 1,
            "deviceid": GL_DEVICEID,
            "uid": GL_UID,
            "bnet_id": "",
            "time": now_time,
            "utm_source": "",
            "event": "layer_add",
            "score": s,
            "layers": s + 1
        }
        params = {
            "_s": str(log_seq),
            "v": "2",
            "_v": "2.2.10",
            "tid": "UA-474506309-10",
            "cid": LOG_SESSION_CID,
            "uid": GL_UID,
            "sr": "393x895",
            "vp": "393x811",
            "de": "UTF-8",
            "sd": "24-bit",
            "ua": log_headers["user-agent"],
            "wasm": "1",
            "ul": "zh-cn",
            "je": "0",
            "t": "event",
            "dl": "https://wp.ds.163.com/minigame/7509fe7f-fde3-4b2a-afa4-ecc86fbded66/index.html?glinnerads_trace_id=69a6c3faa2bc386b6e94802f_1788489827832",
            "dt": "叠叠乐",
            "ec": "act_game_hsti",
            "ea": "fe_act_game_hsti",
            "el": json.dumps(el_payload, separators=(',', ':'), ensure_ascii=False),
            "cd95": LOG_CD95,
            "cd96": LOG_CD96,
            "cd97": round_uuid,
            "z": str(random.randint(100000000, 999999999))
        }

        try:
            res = requests.get(url, params=params, headers=log_headers, timeout=5)
            print(f"[*] [埋点日志] layer_add (第{s+1}层, 当局得分:{s}) | _s:{log_seq} | 状态码:{res.status_code}")
        except Exception as e:
            print(f"[-] [埋点日志] 发送异常: {e}")

        log_seq += 1
        time.sleep(random.uniform(0.1, 0.25))

    return log_seq

def submit_score(score: float, play_time: float) -> bool:
    """
    向上报网关提交数据，成功返回 True，失败返回 False
    """
    url = "https://god-act.gameyw.netease.com/v1/mini-game/datahub/data/obfuscated-batch-write"
    
    # 生成毫秒级时间戳与随机 64 位有符号整型 Nonce
    current_ts = int(time.time() * 1000)
    nonce_val = str(random.randint(-9223372036854775808, 9223372036854775807))
    
    # 组装待加密的业务明文数据
    raw_payload = {
        "miniGameId": MINI_GAME_ID,
        "items": [
            {
                "recordKey": "score_total",
                "value": float(score)
            },
            {
                "recordKey": "play_time",
                "value": float(play_time)
            },
            {
                "recordKey": "last_save",
                "value": current_ts - random.randint(1, 5) # 存档时间微小早于请求时间
            }
        ]
    }
    
    # 执行加密获取 Base64 密文
    encrypted_data = encrypt_game_data(raw_payload, current_ts)
    
    # 最终提交给网关的 Body
    request_body = {
        "data": encrypted_data,
        "ts": current_ts,
        "v": "1.0"
    }
    
    # 严格对齐客户端 WebView 的请求头
    headers = {
        "Host": "god-act.gameyw.netease.com",
        "content-type": "application/json",
        "accept": "application/json, text/plain, */*",
        "gl-version": "4.24.0",
        "gl-source": "URS",
        "gl-uid": GL_UID,
        "gl-deviceid": GL_DEVICEID,
        "gl-token": GL_TOKEN,
        "gl-clienttype": "50",
        "gl-nonce": nonce_val,
        "origin": "https://wp.ds.163.com",
        "referer": "https://wp.ds.163.com/",
        "x-requested-with": "com.netease.gl",
        "user-agent": "Mozilla/5.0 (Linux; Android 13; 23054RA19C Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/111.0.5563.116 Mobile Safari/537.36 Godlike/4.24.0 (channel/wyds_dl_homeholdh5) UEPay/com.netease.gl/android7.13.5",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "accept-encoding": "gzip, deflate",
        "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    # 紧凑序列化单行字符串
    req_str = json.dumps(request_body, ensure_ascii=False)
    payload_str = json.dumps(raw_payload, ensure_ascii=False)
    print(f"[*] [请求] ts:{current_ts} | 目标分:{score} | 目标时长:{play_time}s | 明文:{payload_str} | 报文:{req_str}")

    try:
        response = requests.post(url, headers=headers, json=request_body, timeout=10)
        res_text = response.text.replace("\r", "").replace("\n", " ")
        print(f"[*] [响应] 状态码:{response.status_code} | 报文:{res_text}")
        try:
            res_json = response.json()
            if res_json.get("code") == 200:
                print(f"[+] [成功] 数据版本已推进 -> 当前总分: {int(score)}, 时长: {int(play_time)}s")
                return True
            else:
                print(f"[-] [失败] 错误信息: {res_json.get('errmsg')}")
                return False
        except Exception:
            return False
    except Exception as e:
        print(f"[-] [异常] 网络请求错误: {e}")
        return False

# ==================== 4. 运行模式实现 ====================
def run_auto_mode():
    score, play_time, log_seq = load_game_data()
    print("\n" + "=" * 60)
    print("      光遇叠叠乐小游戏 数据上报工具 (全自动模式)")
    print("=" * 60)
    print(f"[*] 当前初始数据: 总分 = {score} | 累计时长 = {play_time} 秒 | 埋点_s = {log_seq}")
    print(f"[*] 运行策略: 每隔 3~10 秒自动请求一次，基数取 10~20")
    print(f"[*] 行为埋点: 每次上报前模拟发送最后 {LOG_COUNT_PER_ROUND} 层的 layer_add 日志")
    print(f"[*] 提示: 随时按 Ctrl + C 可安全停止并返回主菜单")
    print("=" * 60)
    
    round_count = 0
    try:
        while True:
            round_count += 1
            
            # 1. 请求基数值取 10 ~ 20 随机整数
            base = random.randint(3, 9)
            
            # 2. 游玩时长增加基数值（取整）
            delta_play_time = base
            
            # 3. 比例 1:13，动态随机上下正负 2（即 11.0 ~ 15.0 浮动）
            ratio = round(random.uniform(9.0, 12.0), 2)
            
            # 4. 分数增加 = 基数 * 动态比例（取整）
            delta_score = int(round(base * ratio))
            
            target_score = score + delta_score
            target_play_time = play_time + delta_play_time
            
            print(f"\n--- [第 {round_count} 轮] 基数:{base} | 比例:1:{ratio:.2f} | 增量:时长+{delta_play_time}s, 分数+{delta_score} ---")
            
            # 每次请求前发送行为埋点日志（按增加的分数 delta_score 计算层数与当局分）
            if ENABLE_BURIED_POINT_LOG:
                log_seq = send_game_logs(delta_score, log_seq)

            # 发送上报请求
            success = submit_score(float(target_score), float(target_play_time))
            
            # 每次执行完毕，将最新数据保存到 json
            if success:
                score = target_score
                play_time = target_play_time
                save_game_data(score, play_time, log_seq)
            else:
                print("[-] 本轮上报未成功，不递增本地数据版本，将在下次重试。")
                save_game_data(score, play_time, log_seq)
                
            # 随机等待 3 ~ 10 秒
            sleep_sec = random.randint(15, 30)
            print(f"[*] 等待 {sleep_sec} 秒后自动执行下一轮 (按 Ctrl+C 停止)...")
            time.sleep(sleep_sec)
    except KeyboardInterrupt:
        print("\n[*] 已停止自动循环上报模式，返回主菜单。")

def run_manual_mode():
    score, play_time, log_seq = load_game_data()
    print("\n" + "=" * 60)
    print("      光遇叠叠乐小游戏 数据上报工具 (手动交互模式)")
    print("=" * 60)
    print(f"[*] 提示: 输入 'q' 返回主菜单，输入 'm' 手动修改底数")
    
    while True:
        print("\n" + "-" * 60)
        print(f"【当前数据】 总分: {score}  |  累计时长: {play_time} 秒  |  埋点_s: {log_seq}")
        print("-" * 60)
        
        user_input = input("请输入分数基数 (输入 'q' 返回主菜单，输入 'm' 修改底数): ").strip()
        
        if user_input.lower() in ("q", "quit", "exit"):
            print("[*] 退出手动模式，返回主菜单。")
            break
            
        # 手动校正底数功能
        if user_input.lower() == "m":
            try:
                inp_s = input(f"请输入新的总分 (当前: {score}): ").strip()
                inp_t = input(f"请输入新的累计时长秒数 (当前: {play_time}): ").strip()
                if inp_s:
                    score = int(round(float(inp_s)))
                if inp_t:
                    play_time = int(round(float(inp_t)))
                save_game_data(score, play_time, log_seq)
                print(f"[+] 数据已手动调整 -> 总分: {score}, 时长: {play_time}s")
            except ValueError:
                print("[!] 输入格式有误，已取消修改。")
            continue
            
        try:
            base = float(user_input)
            if base <= 0:
                print("[!] 分数基数应大于 0，请重新输入。")
                continue
        except ValueError:
            print("[!] 请输入有效的数字！")
            continue
            
        # 1. 时长增加基数（取整）
        delta_play_time = int(round(base))
        
        # 2. 比例 1:13，动态随机上下正负 2（即 11.0 ~ 15.0 浮动）
        ratio = round(random.uniform(11.0, 15.0), 2)
        
        # 3. 分数增加 = 基数 * 动态比例（取整）
        delta_score = int(round(base * ratio))
        
        target_score = score + delta_score
        target_play_time = play_time + delta_play_time
        
        print("\n" + "=" * 22 + " [ 本次增量预览 ] " + "=" * 22)
        print(f"  • 输入基数         : {base}")
        print(f"  • 动态随机比例     : 1 : {ratio:.2f} (基准 13 ± 2)")
        print(f"  • 游玩时长增加     : +{delta_play_time}s  -> 目标总时长: {target_play_time}s")
        print(f"  • 分数增加         : +{delta_score}    -> 目标总分: {target_score}")
        print("=" * 64)
        
        confirm = input("确认上报以上数据吗？([Y]/n，回车默认确认提交): ").strip().lower()
        if confirm in ("n", "no"):
            print("[*] 已取消本次上报。")
            continue
            
        # 每次请求前发送行为埋点日志（按增加的分数 delta_score 计算层数与当局分）
        if ENABLE_BURIED_POINT_LOG:
            log_seq = send_game_logs(delta_score, log_seq)

        # 发送上报请求
        success = submit_score(float(target_score), float(target_play_time))
        
        # 每次执行完毕，将最新数据保存到 json
        if success:
            score = target_score
            play_time = target_play_time
            save_game_data(score, play_time, log_seq)
            print(f"[+] 本次上报成功，最新数据已保存！(总分: {score}, 时长: {play_time}s)")
        else:
            force = input("[-] 服务端未确认成功，是否仍要将本次计算的数据保存到本地 JSON？(y/[n]): ").strip().lower()
            if force in ("y", "yes"):
                score = target_score
                play_time = target_play_time
                save_game_data(score, play_time, log_seq)
                print(f"[+] 已强制更新本地 JSON 数据。")

def main():
    while True:
        score, play_time, log_seq = load_game_data()
        print("\n" + "=" * 60)
        print("          光遇叠叠乐小游戏 数据上报工具")
        print("=" * 60)
        print(f"[*] 数据存储文件: {DATA_FILE}")
        print(f"[*] 当前本地数据: 总分 = {score}  |  累计时长 = {play_time} 秒  |  埋点_s = {log_seq}")
        print("-" * 60)
        print("请选择运行模式:")
        print("  [1] 自动循环模式 (每隔 3~10 秒自动上报，基数随机 10~20)")
        print("  [2] 手动交互模式 (自定义输入基数、增量预览并确认提交)")
        print("  [q] 退出程序")
        print("-" * 60)
        
        choice = input("请输入选项编号 [直接回车默认 1]: ").strip().lower()
        
        if choice in ("", "1", "auto"):
            run_auto_mode()
        elif choice in ("2", "manual"):
            run_manual_mode()
        elif choice in ("q", "quit", "exit"):
            print("[*] 程序已退出。")
            break
        else:
            print("[!] 无效选项，请重新输入。")

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n[*] 检测到退出指令，程序已安全退出。最新数据已保存在本地 JSON。")