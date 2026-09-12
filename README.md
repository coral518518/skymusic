# SkyMusic 琴灵 - 光遇全自动弹琴安卓APP

一款专为《光遇》（Sky: Children of the Light）定制的**乐谱导入与全自动模拟弹琴**安卓辅助应用。

---

## ✨ 核心特性

- **免 ROOT / 免电脑激活**：
  基于 Android 官方原生 `AccessibilityService`（无障碍服务）的 `dispatchGesture` API，无需 Root 手机，无需通过电脑 ADB 激活，普通玩家在系统设置中开启无障碍权限即可使用。
- **支持多指并发和弦 (Polyphony)**：
  在单次微秒级手势中同时分发多个触控点，完美演奏双音、三音甚至多重伴奏和弦，绝不卡键、漏音。
- **全机型屏幕分辨率自适应与可视化校准**：
  - 自动识别手机横屏尺寸，自适应计算 15 个钢琴按键的标准中心坐标与行列间距。
  - 支持主流全面屏（20:9、19.5:9、18:9）、标准比例（16:9）及平板（4:3、16:10）。
  - **按键校准浮层**：可在游戏界面上直接呼出 15 个半透明发光光圈，支持微调上下左右平移、行列间距与整体缩放，校准后一键持久化保存。
- **全格式乐谱导入与智能转写（不懂音乐也能弹）**：
  - **光遇专用 JSON 乐谱**（Sky Studio / 光遇社区流行格式）：自动解析 `songNotes` 节点与 `1Key0 ~ 1Key14` 键位。
  - **标准通用 MIDI 音乐文件 (`.mid` / `.midi`)**：可直接导入网上下载的任意流行歌曲 MIDI 伴奏，内置独家**智能调性白键拟合算法**，自动计算最优移调并平移至光遇 15 个自然音阶。
  - **简谱/数字记谱文本**：支持如 `1 2 3 1 | 3 4 5 - | (1 3 5)` 的纯文本乐谱。
- **游戏悬浮控制器**：
  - 极简迷你浮球（可吸附屏幕边缘，不遮挡视线）。
  - 展开式控制面板：实时歌曲名称、进度条拖拽寻道、播放/暂停/停止、0.5x~2.5x 变速、移调（Transpose）与快捷切歌。
- **内置经典预设曲库**：
  - 《小星星》(Twinkle Little Star) - 和弦伴奏版
  - 《千与千寻 - 永远同在》(Always With Me) - 久石让
  - 《天空之城》(Castle in the Sky) - 久石让
  - 《卡农》(Canon in D) - 帕赫贝尔
  - 《起风了》(The Wind Rises)
- **电脑端可视化模拟器 (Web Simulator)**：
  自带即时交互式网页版模拟器，具备 Web Audio 光遇钟琴音效合成、15 键弹奏视觉反馈、分辨率切换与 MIDI/JSON 拖拽试听。

---

## 📂 项目工程结构

```
skymusic/
├── app/
│   ├── src/main/
│   │   ├── AndroidManifest.xml                    # 系统权限声明与服务注册
│   │   ├── res/
│   │   │   ├── xml/accessibility_service_config.xml # 无障碍手势派遣配置 (canPerformGestures)
│   │   │   ├── layout/                            # 主界面、悬浮球、控制面板、校准浮层布局
│   │   │   ├── values/                            # 光遇星空夜景主题配色、字体与多语言文本
│   │   │   └── drawable/                          # 菱形按键、圆球、毛玻璃面板矢量图
│   │   ├── assets/songs/                          # 示范曲目 (.json 与 .mid 样例文件)
│   │   └── java/com/skymusic/player/
│   │       ├── MainActivity.kt                    # 主界面：权限检测引导、曲库管理、文件选择器
│   │       ├── SkyMusicApp.kt                     # Application 上下文与前台通知渠道初始化
│   │       ├── service/
│   │       │   ├── SkyAccessibilityService.kt    # 无障碍点击模拟调度器 (dispatchGesture)
│   │       │   └── FloatingOverlayService.kt      # 游戏悬浮窗生命周期、拖拽与控制面板交互
│   │       ├── engine/
│   │       │   ├── PlayEngine.kt                  # 微秒级高精度播放调度器 (变速/移调/寻道)
│   │       │   └── KeyLayoutManager.kt            # 分辨率计算、15 键坐标数学映射与本地存储
│   │       ├── parser/
│   │       │   ├── SkyJsonParser.kt               # 光遇专属 JSON 乐谱解析器
│   │       │   ├── MidiParser.kt                  # 标准二进制 MIDI 解析与 15 键智能映射
│   │       │   ├── JianpuParser.kt                # 简谱数字记谱文本解析器
│   │       │   └── SheetImporter.kt               # 文件流格式自动识别入口
│   │       ├── model/
│   │       │   ├── Song.kt                        # 乐谱歌曲模型
│   │       │   ├── NoteEvent.kt                   # 音符打击事件（支持多音并发和弦）
│   │       │   └── KeyLayoutConfig.kt             # 屏幕长宽比与坐标布局参数
│   │       ├── ui/
│   │       │   ├── KeyVisualizerView.kt           # 15 个发光光圈自定义 View
│   │       │   └── SongAdapter.kt                 # 曲库列表 RecyclerView 适配器
│   │       └── util/
│   │           ├── PermissionHelper.kt            # 悬浮窗与无障碍服务权限检测与跳转
│   │           └── PresetSongs.kt                 # 内置精品示范乐谱
│   └── build.gradle.kts
├── simulator/                                     # 本地即时网页模拟器与调试工具
│   ├── index.html                                 # 模拟手机横屏、光遇钢琴、悬浮窗
│   ├── app.js                                     # Web Audio 合成器、MIDI/JSON 解析器
│   └── style.css                                  # 极简奢华暗黑玻璃拟态设计
├── scripts/
│   ├── generate_midi.py                           # 示范 MIDI 生成脚本
│   └── test_engine.py                             # 乐谱解析与坐标计算自动化测试脚本
├── build.gradle.kts
├── settings.gradle.kts
└── gradle.properties
```

---

## 🛠️ 如何在 Android Studio 中编译打包

1. 用 **Android Studio** 打开 `e:/work/skymusic` 目录。
2. 等待 Gradle 自动完成依赖同步（Gradle 8.3.2 + Kotlin 1.9.23，JDK 17）。
3. 连接安卓手机（Android 7.0 及以上版本）并开启 USB 调试。
4. 点击顶部的 **Run 'app'**（或菜单栏 `Build` -> `Build Bundle(s) / APK(s)` -> `Build APK(s)`）。
5. 将生成的 APK 安装到手机上即可。

---

## 📱 手机端使用指南

1. **首次打开 App**：
   - 点击「无障碍点击服务」右侧的「去开启」，在系统设置列表中找到 **SkyMusic 琴灵** 并勾选允许。
   - 点击「游戏悬浮窗权限」右侧的「去开启」，在系统设置中允许在其他应用上层显示。
2. **选择或导入乐谱**：
   - 可以在「精选预设」中直接挑选曲目。
   - 或点击右上角「+ 导入乐谱」，选择手机存储中的 `.mid`（MIDI 文件）或 `.json`（Sky Studio 导出的乐谱）。
3. **启动游戏与弹琴**：
   - 点击主界面醒目的金色大按钮「启动游戏悬浮窗」。
   - 打开《光遇》游戏，前往遇境或任意地图，掏出钢琴或竖琴。
   - 屏幕上会有一个发光的浮球，轻触即可展开控制器。
   - 第一次使用时点击控制器右上角的「⚙️ 校准」图标，屏幕上会浮现 15 个发光光圈。点击「一键自动对齐」或者通过上下左右微调按钮让光圈准确套入光遇琴键，点击「保存并完成」。
   - 点击播放按钮（▶），APP 便会按照精准节拍自动为您在游戏中弹奏出动听的音乐！

---

## 💻 电脑端即时体验模拟器

如果您手头没有手机，可在电脑端直接体验：
```bash
# 启动本地网页服务
python -m http.server 8088 --directory e:\work\skymusic\simulator
```
在浏览器中访问 `http://localhost:8088/` 即可：
- 自由点击 15 个菱形按键体验空灵琴音。
- 试听内置的《小星星》、《千与千寻》、《天空之城》、《卡农》。
- 拖拽任意 MIDI 或 JSON 乐谱导入试听。
- 切换 16:9、19.5:9、20:9、平板等各种屏幕比例观察 15 键自适应效果。
