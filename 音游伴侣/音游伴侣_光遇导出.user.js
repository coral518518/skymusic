// ==UserScript==
// @name         音游伴侣 - 乐谱导出与已下载管理 (官方Scores标准格式)
// @namespace    https://mgm.jie-you.cn/
// @version      1.2.0
// @description  自动捕获网页端解密乐谱，识别已下载状态，一键导出与 scores 文件夹内格式完全一致的 JSON 并自动维护 downloaded_ids.json
// @author       SkyMusic Helper
// @match        https://mgm.jie-you.cn/*
// @run-at       document-start
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_setClipboard
// @grant        unsafeWindow
// ==/UserScript==

(function () {
    'use strict';

    const targetWindow = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;

    // 默认内置的本地已下载记录（初始同步自 downloaded_ids.json）
    const DEFAULT_INDEX_DATA = { "last_updated": "2026-09-17 03:33:23", "total_downloaded": 154, "ids": [20, 1136, 1781, 2224, 2314, 2411, 3330, 3472, 3657, 4126, 4184, 4262, 4323, 5028, 5040, 5043, 5419, 5701, 6026, 7100, 7247, 7250, 7465, 7623, 7744, 7902, 8115, 8709, 8764, 8771, 9020, 9382, 11816, 12015, 12179, 12429, 12720, 12841, 13084, 13150, 14186, 14191, 15117, 17245, 23777, 28829, 29218, 30405, 32160, 32170, 32194, 32208, 32603, 32635, 33729, 33730, 33733, 33918, 34185, 36420, 37063, 38210, 38277, 38319, 38863, 38898, 39066, 39076, 39083, 39085, 39105, 39107, 39108, 39110, 39118, 39124, 39130, 39139, 39140, 39147, 39148, 39151, 39152, 39155, 39156, 39162, 39163, 39165, 39200, 39201, 39209, 39211, 39212, 39214, 39228, 39243, 39249, 39258, 39266, 39268, 39278, 39282, 39283, 39284, 39287, 39289, 39296, 39299, 39300, 39306, 39318, 39331, 39337, 39345, 39348, 39366, 39368, 39371, 39408, 39411, 39459, 39566, 39569, 39570, 39646, 39647, 39649, 39654, 39661, 39675, 39763, 39785, 39804, 39848, 39866, 39879, 39889, 39899, 39922, 39972, 39983, 40044, 40047, 40058, 40068, 40074, 40122, 40130, 40136, 40138, 40159, 40261, 40306, 40310], "records": { "32208": { "title": "唯一-邓紫棋", "json_file": "32208_唯一-邓紫棋.json", "txt_file": "32208_唯一-邓紫棋_简谱.txt", "download_time": "2026-09-15 15:33:29" }, "38863": { "title": "Luvsic", "json_file": "38863_Luvsic.json", "txt_file": "38863_Luvsic_简谱.txt", "download_time": "2026-09-15 15:33:41" }, "5040": { "title": "诀别书纯间奏版", "json_file": "5040_诀别书纯间奏版.json", "txt_file": "5040_诀别书纯间奏版_简谱.txt", "download_time": "2026-09-15 15:33:54" }, "32170": { "title": "偏爱", "json_file": "32170_偏爱.json", "txt_file": "32170_偏爱_简谱.txt", "download_time": "2026-09-15 15:34:06" }, "39214": { "title": "鸟之诗-部分仿A叔", "json_file": "39214_鸟之诗-部分仿A叔.json", "txt_file": "39214_鸟之诗-部分仿A叔_简谱.txt", "download_time": "2026-09-15 07:50:50" }, "4262": { "title": "坏女孩3", "json_file": "4262_坏女孩3.json", "txt_file": "4262_坏女孩3_简谱.txt", "download_time": "2026-09-15 07:51:11" }, "9382": { "title": "溯reverse1", "json_file": "9382_溯reverse1.json", "txt_file": "9382_溯reverse1_简谱.txt", "download_time": "2026-09-15 07:51:33" }, "39200": { "title": "Flower-Dance-花之舞", "json_file": "39200_Flower-Dance-花之舞.json", "txt_file": "39200_Flower-Dance-花之舞_简谱.txt", "download_time": "2026-09-15 07:51:56" }, "20": { "title": "你的名字-约会", "json_file": "20_你的名字-约会.json", "txt_file": "20_你的名字-约会_简谱.txt", "download_time": "2026-09-15 07:52:18" }, "2411": { "title": "第57次取消发送1", "json_file": "2411_第57次取消发送1.json", "txt_file": "2411_第57次取消发送1_简谱.txt", "download_time": "2026-09-15 07:52:40" }, "29218": { "title": "Time-machine3", "json_file": "29218_Time-machine3.json", "txt_file": "29218_Time-machine3_简谱.txt", "download_time": "2026-09-15 07:53:01" }, "39110": { "title": "Sacred-Play-Secret-Place", "json_file": "39110_Sacred-Play-Secret-Place.json", "txt_file": "39110_Sacred-Play-Secret-Place_简谱.txt", "download_time": "2026-09-15 07:53:22" }, "39155": { "title": "反乌托邦", "json_file": "39155_反乌托邦.json", "txt_file": "39155_反乌托邦_简谱.txt", "download_time": "2026-09-15 07:53:43" }, "33729": { "title": "时间煮雨-四人合奏谱", "json_file": "33729_时间煮雨-四人合奏谱.json", "txt_file": "33729_时间煮雨-四人合奏谱_简谱.txt", "download_time": "2026-09-15 07:54:05" }, "5701": { "title": "恋人", "json_file": "5701_恋人.json", "txt_file": "5701_恋人_简谱.txt", "download_time": "2026-09-15 08:17:18" }, "8764": { "title": "圣诞快乐劳伦斯先生-小提琴", "json_file": "8764_圣诞快乐劳伦斯先生-小提琴.json", "txt_file": "8764_圣诞快乐劳伦斯先生-小提琴_简谱.txt", "download_time": "2026-09-15 08:17:34" }, "39570": { "title": "蒲公英的约定-三指完整版", "json_file": "39570_蒲公英的约定-三指完整版.json", "txt_file": "39570_蒲公英的约定-三指完整版_简谱.txt", "download_time": "2026-09-15 08:17:52" }, "39124": { "title": "小半", "json_file": "39124_小半.json", "txt_file": "39124_小半_简谱.txt", "download_time": "2026-09-15 08:18:08" }, "39899": { "title": "感官过载", "json_file": "39899_感官过载.json", "txt_file": "39899_感官过载_简谱.txt", "download_time": "2026-09-15 08:18:25" }, "12429": { "title": "夜萤火虫和你", "json_file": "12429_夜萤火虫和你.json", "txt_file": "12429_夜萤火虫和你_简谱.txt", "download_time": "2026-09-15 08:18:42" }, "14186": { "title": "最后一页1", "json_file": "14186_最后一页1.json", "txt_file": "14186_最后一页1_简谱.txt", "download_time": "2026-09-15 08:19:08" }, "39147": { "title": "千本樱", "json_file": "39147_千本樱.json", "txt_file": "39147_千本樱_简谱.txt", "download_time": "2026-09-15 08:19:24" }, "13150": { "title": "雨爱6", "json_file": "13150_雨爱6.json", "txt_file": "13150_雨爱6_简谱.txt", "download_time": "2026-09-15 08:19:41" }, "1781": { "title": "穿越时空的思念笛子", "json_file": "1781_穿越时空的思念笛子.json", "txt_file": "1781_穿越时空的思念笛子_简谱.txt", "download_time": "2026-09-15 08:19:56" }, "32160": { "title": "红色高跟鞋2", "json_file": "32160_红色高跟鞋2.json", "txt_file": "32160_红色高跟鞋2_简谱.txt", "download_time": "2026-09-15 08:20:13" }, "7100": { "title": "鸟之诗-伤感抒情版-鳥の詩-とりのうた1", "json_file": "7100_鸟之诗-伤感抒情版-鳥の詩-とりのうた1.json", "txt_file": "7100_鸟之诗-伤感抒情版-鳥の詩-とりのうた1_简谱.txt", "download_time": "2026-09-15 08:20:30" }, "39459": { "title": "time-machine", "json_file": "39459_time-machine.json", "txt_file": "39459_time-machine_简谱.txt", "download_time": "2026-09-15 08:20:46" }, "4323": { "title": "荒-我曾爱上一个人-笛子版", "json_file": "4323_荒-我曾爱上一个人-笛子版.json", "txt_file": "4323_荒-我曾爱上一个人-笛子版_简谱.txt", "download_time": "2026-09-15 08:21:03" }, "2314": { "title": "稻香-周杰伦", "json_file": "2314_稻香-周杰伦.json", "txt_file": "2314_稻香-周杰伦_简谱.txt", "download_time": "2026-09-15 08:21:18" }, "33733": { "title": "《幻昼》5乐器合奏谱", "json_file": "33733_《幻昼》5乐器合奏谱.json", "txt_file": "33733_《幻昼》5乐器合奏谱_简谱.txt", "download_time": "2026-09-16 05:27:30" }, "12841": { "title": "樱花草2", "json_file": "12841_樱花草2.json", "txt_file": "12841_樱花草2_简谱.txt", "download_time": "2026-09-16 05:30:34" }, "39318": { "title": "Are you lost 二创", "json_file": "39318_Are you lost 二创.json", "txt_file": "39318_Are you lost 二创_简谱.txt", "download_time": "2026-09-16 05:33:37" }, "32635": { "title": "鸟之诗", "json_file": "32635_鸟之诗.json", "txt_file": "32635_鸟之诗_简谱.txt", "download_time": "2026-09-16 05:36:38" }, "39284": { "title": "Call of Silence", "json_file": "39284_Call of Silence.json", "txt_file": "39284_Call of Silence_简谱.txt", "download_time": "2026-09-16 05:39:42" }, "39331": { "title": "圣诞快乐劳伦斯先生 (2)", "json_file": "39331_圣诞快乐劳伦斯先生 (2).json", "txt_file": "39331_圣诞快乐劳伦斯先生 (2)_简谱.txt", "download_time": "2026-09-16 05:42:46" }, "14191": { "title": "最后一页4", "json_file": "14191_最后一页4.json", "txt_file": "14191_最后一页4_简谱.txt", "download_time": "2026-09-16 05:45:49" }, "39296": { "title": "葬花", "json_file": "39296_葬花.json", "txt_file": "39296_葬花_简谱.txt", "download_time": "2026-09-16 05:48:51" }, "36420": { "title": "Take Me Hand", "json_file": "36420_Take Me Hand.json", "txt_file": "36420_Take Me Hand_简谱.txt", "download_time": "2026-09-16 05:51:54" }, "38210": { "title": "海屿你", "json_file": "38210_海屿你.json", "txt_file": "38210_海屿你_简谱.txt", "download_time": "2026-09-16 05:54:56" }, "39201": { "title": "花海", "json_file": "39201_花海.json", "txt_file": "39201_花海_简谱.txt", "download_time": "2026-09-16 06:05:17" }, "5043": { "title": "诀别书完整版", "json_file": "5043_诀别书完整版.json", "txt_file": "5043_诀别书完整版_简谱.txt", "download_time": "2026-09-16 06:05:55" }, "32603": { "title": "蜜雪冰城甜蜜蜜-蜜雪冰城主题曲-你爱我我爱你蜜雪冰城甜蜜蜜-抖音", "json_file": "32603_蜜雪冰城甜蜜蜜-蜜雪冰城主题曲-你爱我我爱你蜜雪冰城甜蜜蜜-抖音.json", "txt_file": "32603_蜜雪冰城甜蜜蜜-蜜雪冰城主题曲-你爱我我爱你蜜雪冰城甜蜜蜜-抖音_简谱.txt", "download_time": "2026-09-16 06:06:32" }, "39306": { "title": "罗生门", "json_file": "39306_罗生门.json", "txt_file": "39306_罗生门_简谱.txt", "download_time": "2026-09-16 06:07:14" }, "7465": { "title": "起风了 高度还原", "json_file": "7465_起风了 高度还原.json", "txt_file": "7465_起风了 高度还原_简谱.txt", "download_time": "2026-09-16 06:08:00" }, "39866": { "title": "情绪回收站-失落花园", "json_file": "39866_情绪回收站-失落花园.json", "txt_file": "39866_情绪回收站-失落花园_简谱.txt", "download_time": "2026-09-16 06:08:42" }, "39148": { "title": "愿与愁", "json_file": "39148_愿与愁.json", "txt_file": "39148_愿与愁_简谱.txt", "download_time": "2026-09-16 06:09:24" }, "39211": { "title": "This is what sadness feels like", "json_file": "39211_This is what sadness feels like.json", "txt_file": "39211_This is what sadness feels like_简谱.txt", "download_time": "2026-09-16 06:10:02" }, "12015": { "title": "悬溺(片段)", "json_file": "12015_悬溺(片段).json", "txt_file": "12015_悬溺(片段)_简谱.txt", "download_time": "2026-09-16 06:10:39" }, "33730": { "title": "《青花瓷》三人合奏谱", "json_file": "33730_《青花瓷》三人合奏谱.json", "txt_file": "33730_《青花瓷》三人合奏谱_简谱.txt", "download_time": "2026-09-16 06:11:17" }, "39366": { "title": "我不曾忘记 原神", "json_file": "39366_我不曾忘记 原神.json", "txt_file": "39366_我不曾忘记 原神_简谱.txt", "download_time": "2026-09-16 06:11:56" }, "39140": { "title": "囍（Sky.毅轮指版）", "json_file": "39140_囍（Sky.毅轮指版）.json", "txt_file": "39140_囍（Sky.毅轮指版）_简谱.txt", "download_time": "2026-09-16 06:12:34" }, "39569": { "title": "失眠 - Suki刘舒妤", "json_file": "39569_失眠 - Suki刘舒妤.json", "txt_file": "39569_失眠 - Suki刘舒妤_简谱.txt", "download_time": "2026-09-16 06:13:12" }, "39300": { "title": "多远都要在一起", "json_file": "39300_多远都要在一起.json", "txt_file": "39300_多远都要在一起_简谱.txt", "download_time": "2026-09-16 06:13:48" }, "40261": { "title": "Mr.\"Broken Heart\"", "json_file": "40261_Mr._Broken Heart_.json", "txt_file": "40261_Mr._Broken Heart__简谱.txt", "download_time": "2026-09-16 06:14:30" }, "39408": { "title": "清醒梦", "json_file": "39408_清醒梦.json", "txt_file": "39408_清醒梦_简谱.txt", "download_time": "2026-09-17 01:30:15" }, "39289": { "title": "无人之岛", "json_file": "39289_无人之岛.json", "txt_file": "39289_无人之岛_简谱.txt", "download_time": "2026-09-17 01:31:32" }, "12179": { "title": "眼鼻嘴", "json_file": "12179_眼鼻嘴.json", "txt_file": "12179_眼鼻嘴_简谱.txt", "download_time": "2026-09-17 01:32:45" }, "7623": { "title": "牵丝戏♡", "json_file": "7623_牵丝戏♡.json", "txt_file": "7623_牵丝戏♡_简谱.txt", "download_time": "2026-09-17 01:34:00" }, "39983": { "title": "夏日尽头的我们", "json_file": "39983_夏日尽头的我们.json", "txt_file": "39983_夏日尽头的我们_简谱.txt", "download_time": "2026-09-17 01:35:15" }, "40058": { "title": "LightingMoment", "json_file": "40058_LightingMoment.json", "txt_file": "40058_LightingMoment_简谱.txt", "download_time": "2026-09-17 01:36:32" }, "39105": { "title": "童话镇", "json_file": "39105_童话镇.json", "txt_file": "39105_童话镇_简谱.txt", "download_time": "2026-09-17 01:37:46" }, "34185": { "title": "Are you lost2", "json_file": "34185_Are you lost2.json", "txt_file": "34185_Are you lost2_简谱.txt", "download_time": "2026-09-17 01:38:59" }, "39165": { "title": "nop", "json_file": "39165_nop.json", "txt_file": "39165_nop_简谱.txt", "download_time": "2026-09-17 01:40:12" }, "38319": { "title": "麻醉师 (3)", "json_file": "38319_麻醉师 (3).json", "txt_file": "38319_麻醉师 (3)_简谱.txt", "download_time": "2026-09-17 01:41:26" }, "39371": { "title": "起风了", "json_file": "39371_起风了.json", "txt_file": "39371_起风了_简谱.txt", "download_time": "2026-09-17 01:42:39" }, "39654": { "title": "感官过载", "json_file": "39654_感官过载.json", "txt_file": "39654_感官过载_简谱.txt", "download_time": "2026-09-17 01:43:57" }, "39804": { "title": "左边画个虫虫", "json_file": "39804_左边画个虫虫.json", "txt_file": "39804_左边画个虫虫_简谱.txt", "download_time": "2026-09-17 01:45:10" }, "39212": { "title": "Towards the light", "json_file": "39212_Towards the light.json", "txt_file": "39212_Towards the light_简谱.txt", "download_time": "2026-09-17 01:46:26" }, "13084": { "title": "于是5", "json_file": "13084_于是5.json", "txt_file": "13084_于是5_简谱.txt", "download_time": "2026-09-17 01:47:41" }, "39249": { "title": "鸟之诗-A叔版", "json_file": "39249_鸟之诗-A叔版.json", "txt_file": "39249_鸟之诗-A叔版_简谱.txt", "download_time": "2026-09-17 01:48:56" }, "39889": { "title": "你就是我的风景-何洁", "json_file": "39889_你就是我的风景-何洁.json", "txt_file": "39889_你就是我的风景-何洁_简谱.txt", "download_time": "2026-09-17 01:50:09" }, "7247": { "title": "琵琶行4", "json_file": "7247_琵琶行4.json", "txt_file": "7247_琵琶行4_简谱.txt", "download_time": "2026-09-17 01:51:22" }, "39972": { "title": "甲乙丙丁", "json_file": "39972_甲乙丙丁.json", "txt_file": "39972_甲乙丙丁_简谱.txt", "download_time": "2026-09-17 01:52:36" }, "38898": { "title": "one last kiss", "json_file": "38898_one last kiss.json", "txt_file": "38898_one last kiss_简谱.txt", "download_time": "2026-09-17 01:53:52" }, "32194": { "title": "Faded1", "json_file": "32194_Faded1.json", "txt_file": "32194_Faded1_简谱.txt", "download_time": "2026-09-17 01:55:04" }, "39922": { "title": "Always online-林俊杰", "json_file": "39922_Always online-林俊杰.json", "txt_file": "39922_Always online-林俊杰_简谱.txt", "download_time": "2026-09-17 01:56:19" }, "39228": { "title": "This is what sadness feels like", "json_file": "39228_This is what sadness feels like.json", "txt_file": "39228_This is what sadness feels like_简谱.txt", "download_time": "2026-09-17 01:57:32" }, "28829": { "title": "The truth that you leave你离开的事实", "json_file": "28829_The truth that you leave你离开的事实.json", "txt_file": "28829_The truth that you leave你离开的事实_简谱.txt", "download_time": "2026-09-17 01:58:46" }, "39076": { "title": "《晴天》9轨合奏谱", "json_file": "39076_《晴天》9轨合奏谱.json", "txt_file": "39076_《晴天》9轨合奏谱_简谱.txt", "download_time": "2026-09-17 02:00:00" }, "5419": { "title": "兰亭序-周杰伦", "json_file": "5419_兰亭序-周杰伦.json", "txt_file": "5419_兰亭序-周杰伦_简谱.txt", "download_time": "2026-09-17 02:01:18" }, "33918": { "title": "圣诞快乐劳伦斯先生 (by 光遇sky 晞。)", "json_file": "33918_圣诞快乐劳伦斯先生 (by 光遇sky 晞。).json", "txt_file": "33918_圣诞快乐劳伦斯先生 (by 光遇sky 晞。)_简谱.txt", "download_time": "2026-09-17 02:02:32" }, "11816": { "title": "星光下的梦想2", "json_file": "11816_星光下的梦想2.json", "txt_file": "11816_星光下的梦想2_简谱.txt", "download_time": "2026-09-17 02:03:46" }, "39139": { "title": "时间煮雨", "json_file": "39139_时间煮雨.json", "txt_file": "39139_时间煮雨_简谱.txt", "download_time": "2026-09-17 02:05:00" }, "7902": { "title": "晴天9", "json_file": "7902_晴天9.json", "txt_file": "7902_晴天9_简谱.txt", "download_time": "2026-09-17 02:06:13" }, "40122": { "title": "花之舞", "json_file": "40122_花之舞.json", "txt_file": "40122_花之舞_简谱.txt", "download_time": "2026-09-17 02:07:26" }, "39337": { "title": "china-x", "json_file": "39337_china-x.json", "txt_file": "39337_china-x_简谱.txt", "download_time": "2026-09-17 02:08:41" }, "23777": { "title": "MIUI铃声(循环)", "json_file": "23777_MIUI铃声(循环).json", "txt_file": "23777_MIUI铃声(循环)_简谱.txt", "download_time": "2026-09-17 02:09:54" }, "39848": { "title": "恋人-李荣浩", "json_file": "39848_恋人-李荣浩.json", "txt_file": "39848_恋人-李荣浩_简谱.txt", "download_time": "2026-09-17 02:11:09" }, "5028": { "title": "诀别书(完整版)", "json_file": "5028_诀别书(完整版).json", "txt_file": "5028_诀别书(完整版)_简谱.txt", "download_time": "2026-09-17 02:12:22" }, "17245": { "title": "Cry for me2", "json_file": "17245_Cry for me2.json", "txt_file": "17245_Cry for me2_简谱.txt", "download_time": "2026-09-17 02:13:37" }, "39258": { "title": "Undertale", "json_file": "39258_Undertale.json", "txt_file": "39258_Undertale_简谱.txt", "download_time": "2026-09-17 02:14:50" }, "12720": { "title": "义勇军进行曲-中华人民共和国国歌", "json_file": "12720_义勇军进行曲-中华人民共和国国歌.json", "txt_file": "12720_义勇军进行曲-中华人民共和国国歌_简谱.txt", "download_time": "2026-09-17 02:16:05" }, "8771": { "title": "圣诞快乐劳伦斯先生5", "json_file": "8771_圣诞快乐劳伦斯先生5.json", "txt_file": "8771_圣诞快乐劳伦斯先生5_简谱.txt", "download_time": "2026-09-17 02:17:19" }, "39661": { "title": "感官过载 低高音双琴 15键还原稿", "json_file": "39661_感官过载 低高音双琴 15键还原稿.json", "txt_file": "39661_感官过载 低高音双琴 15键还原稿_简谱.txt", "download_time": "2026-09-17 02:18:32" }, "39108": { "title": "归零", "json_file": "39108_归零.json", "txt_file": "39108_归零_简谱.txt", "download_time": "2026-09-17 02:19:46" }, "3472": { "title": "关键词-林俊杰", "json_file": "3472_关键词-林俊杰.json", "txt_file": "3472_关键词-林俊杰_简谱.txt", "download_time": "2026-09-17 02:21:02" }, "4126": { "title": "花海周杰伦1", "json_file": "4126_花海周杰伦1.json", "txt_file": "4126_花海周杰伦1_简谱.txt", "download_time": "2026-09-17 02:22:16" }, "39156": { "title": "Nevada", "json_file": "39156_Nevada.json", "txt_file": "39156_Nevada_简谱.txt", "download_time": "2026-09-17 02:23:35" }, "1136": { "title": "宾克斯的美酒1", "json_file": "1136_宾克斯的美酒1.json", "txt_file": "1136_宾克斯的美酒1_简谱.txt", "download_time": "2026-09-17 02:24:49" }, "39348": { "title": "原神少女哥伦比娅主题曲 银月之庭", "json_file": "39348_原神少女哥伦比娅主题曲 银月之庭.json", "txt_file": "39348_原神少女哥伦比娅主题曲 银月之庭_简谱.txt", "download_time": "2026-09-17 02:26:03" }, "39368": { "title": "晴天", "json_file": "39368_晴天.json", "txt_file": "39368_晴天_简谱.txt", "download_time": "2026-09-17 02:27:20" }, "39268": { "title": "His Theme", "json_file": "39268_His Theme.json", "txt_file": "39268_His Theme_简谱.txt", "download_time": "2026-09-17 02:28:33" }, "39085": { "title": "米塔の小曲", "json_file": "39085_米塔の小曲.json", "txt_file": "39085_米塔の小曲_简谱.txt", "download_time": "2026-09-17 02:29:46" }, "38277": { "title": "卡农-小提琴", "json_file": "38277_卡农-小提琴.json", "txt_file": "38277_卡农-小提琴_简谱.txt", "download_time": "2026-09-17 02:31:02" }, "39209": { "title": "盛夏的果实（升级版）", "json_file": "39209_盛夏的果实（升级版）.json", "txt_file": "39209_盛夏的果实（升级版）_简谱.txt", "download_time": "2026-09-17 02:32:17" }, "39066": { "title": "angel（片段）", "json_file": "39066_angel（片段）.json", "txt_file": "39066_angel（片段）_简谱.txt", "download_time": "2026-09-17 02:33:30" }, "6026": { "title": "罗生门-Harper", "json_file": "6026_罗生门-Harper.json", "txt_file": "6026_罗生门-Harper_简谱.txt", "download_time": "2026-09-17 02:34:43" }, "39287": { "title": "原神（皎洁的笑颜）合奏版", "json_file": "39287_原神（皎洁的笑颜）合奏版.json", "txt_file": "39287_原神（皎洁的笑颜）合奏版_简谱.txt", "download_time": "2026-09-17 02:35:56" }, "39162": { "title": "深海少女", "json_file": "39162_深海少女.json", "txt_file": "39162_深海少女_简谱.txt", "download_time": "2026-09-17 02:37:09" }, "39152": { "title": "何以歌", "json_file": "39152_何以歌.json", "txt_file": "39152_何以歌_简谱.txt", "download_time": "2026-09-17 02:38:22" }, "39299": { "title": "golden hour", "json_file": "39299_golden hour.json", "txt_file": "39299_golden hour_简谱.txt", "download_time": "2026-09-17 02:39:40" }, "7744": { "title": "青花瓷(吉他或者琵琶效果更好)", "json_file": "7744_青花瓷(吉他或者琵琶效果更好).json", "txt_file": "7744_青花瓷(吉他或者琵琶效果更好)_简谱.txt", "download_time": "2026-09-17 02:40:55" }, "40044": { "title": "你离开的事实", "json_file": "40044_你离开的事实.json", "txt_file": "40044_你离开的事实_简谱.txt", "download_time": "2026-09-17 02:42:09" }, "39879": { "title": "静悄悄(1)", "json_file": "39879_静悄悄(1).json", "txt_file": "39879_静悄悄(1)_简谱.txt", "download_time": "2026-09-17 02:43:27" }, "39163": { "title": "Lullaby", "json_file": "39163_Lullaby.json", "txt_file": "39163_Lullaby_简谱.txt", "download_time": "2026-09-17 02:44:40" }, "2224": { "title": "单手诀别书 (az)", "json_file": "2224_单手诀别书 (az).json", "txt_file": "2224_单手诀别书 (az)_简谱.txt", "download_time": "2026-09-17 02:45:57" }, "39646": { "title": "《We Don't Talk Anymore》5乐器合奏", "json_file": "39646_《We Don't Talk Anymore》5乐器合奏.json", "txt_file": "39646_《We Don't Talk Anymore》5乐器合奏_简谱.txt", "download_time": "2026-09-17 02:47:11" }, "40159": { "title": "虫儿飞 萌新入门歌曲", "json_file": "40159_虫儿飞 萌新入门歌曲.json", "txt_file": "40159_虫儿飞 萌新入门歌曲_简谱.txt", "download_time": "2026-09-17 02:48:24" }, "39785": { "title": "虚拟-陈粒", "json_file": "39785_虚拟-陈粒.json", "txt_file": "39785_虚拟-陈粒_简谱.txt", "download_time": "2026-09-17 02:49:39" }, "39283": { "title": "快乐的扑满 简易版", "json_file": "39283_快乐的扑满 简易版.json", "txt_file": "39283_快乐的扑满 简易版_简谱.txt", "download_time": "2026-09-17 02:50:55" }, "39566": { "title": "强军战歌", "json_file": "39566_强军战歌.json", "txt_file": "39566_强军战歌_简谱.txt", "download_time": "2026-09-17 02:52:10" }, "39130": { "title": "Eutopia(轮指)", "json_file": "39130_Eutopia(轮指).json", "txt_file": "39130_Eutopia(轮指)_简谱.txt", "download_time": "2026-09-17 02:53:26" }, "37063": { "title": "巴拉莱卡", "json_file": "37063_巴拉莱卡.json", "txt_file": "37063_巴拉莱卡_简谱.txt", "download_time": "2026-09-17 02:54:44" }, "40138": { "title": "浴室-DoubleMirror双面镜", "json_file": "40138_浴室-DoubleMirror双面镜.json", "txt_file": "40138_浴室-DoubleMirror双面镜_简谱.txt", "download_time": "2026-09-17 02:56:00" }, "39266": { "title": "《Bad Apple》 交响乐版", "json_file": "39266_《Bad Apple》 交响乐版.json", "txt_file": "39266_《Bad Apple》 交响乐版_简谱.txt", "download_time": "2026-09-17 02:57:15" }, "8709": { "title": "生日快乐歌1", "json_file": "8709_生日快乐歌1.json", "txt_file": "8709_生日快乐歌1_简谱.txt", "download_time": "2026-09-17 02:58:29" }, "39675": { "title": "第57次取消发送", "json_file": "39675_第57次取消发送.json", "txt_file": "39675_第57次取消发送_简谱.txt", "download_time": "2026-09-17 02:59:43" }, "8115": { "title": "人鱼的眼泪-EXO", "json_file": "8115_人鱼的眼泪-EXO.json", "txt_file": "8115_人鱼的眼泪-EXO_简谱.txt", "download_time": "2026-09-17 03:00:56" }, "40306": { "title": "anybody can find love", "json_file": "40306_anybody can find love.json", "txt_file": "40306_anybody can find love_简谱.txt", "download_time": "2026-09-17 03:02:14" }, "39345": { "title": "罗小黑（嘘）", "json_file": "39345_罗小黑（嘘）.json", "txt_file": "39345_罗小黑（嘘）_简谱.txt", "download_time": "2026-09-17 03:03:27" }, "39107": { "title": "依兰爱情故事", "json_file": "39107_依兰爱情故事.json", "txt_file": "39107_依兰爱情故事_简谱.txt", "download_time": "2026-09-17 03:04:40" }, "39763": { "title": "琵琶行（琵琶片段）", "json_file": "39763_琵琶行（琵琶片段）.json", "txt_file": "39763_琵琶行（琵琶片段）_简谱.txt", "download_time": "2026-09-17 03:05:53" }, "39118": { "title": "匆匆那年（升级版）", "json_file": "39118_匆匆那年（升级版）.json", "txt_file": "39118_匆匆那年（升级版）_简谱.txt", "download_time": "2026-09-17 03:07:07" }, "3330": { "title": "篝火旁", "json_file": "3330_篝火旁.json", "txt_file": "3330_篝火旁_简谱.txt", "download_time": "2026-09-17 03:08:20" }, "40068": { "title": "麻醉师（高燃还原）", "json_file": "40068_麻醉师（高燃还原）.json", "txt_file": "40068_麻醉师（高燃还原）_简谱.txt", "download_time": "2026-09-17 03:09:38" }, "39243": { "title": "月が美しいと聞きたいです［悍妇］", "json_file": "39243_月が美しいと聞きたいです［悍妇］.json", "txt_file": "39243_月が美しいと聞きたいです［悍妇］_简谱.txt", "download_time": "2026-09-17 03:10:52" }, "30405": { "title": "we don't talk anymore3", "json_file": "30405_we don't talk anymore3.json", "txt_file": "30405_we don't talk anymore3_简谱.txt", "download_time": "2026-09-17 03:12:08" }, "7250": { "title": "偏爱-张芸京-仙剑奇侠传", "json_file": "7250_偏爱-张芸京-仙剑奇侠传.json", "txt_file": "7250_偏爱-张芸京-仙剑奇侠传_简谱.txt", "download_time": "2026-09-17 03:13:23" }, "4184": { "title": "花之舞 Flower Dance", "json_file": "4184_花之舞 Flower Dance.json", "txt_file": "4184_花之舞 Flower Dance_简谱.txt", "download_time": "2026-09-17 03:14:41" }, "3657": { "title": "海海海3", "json_file": "3657_海海海3.json", "txt_file": "3657_海海海3_简谱.txt", "download_time": "2026-09-17 03:15:55" }, "39083": { "title": "Sacred Play Secret Place10种乐器合奏", "json_file": "39083_Sacred Play Secret Place10种乐器合奏.json", "txt_file": "39083_Sacred Play Secret Place10种乐器合奏_简谱.txt", "download_time": "2026-09-17 03:17:10" }, "40136": { "title": "Daylight", "json_file": "40136_Daylight.json", "txt_file": "40136_Daylight_简谱.txt", "download_time": "2026-09-17 03:18:28" }, "40047": { "title": "我好想你-苏打绿", "json_file": "40047_我好想你-苏打绿.json", "txt_file": "40047_我好想你-苏打绿_简谱.txt", "download_time": "2026-09-17 03:19:41" }, "39647": { "title": "诀别书", "json_file": "39647_诀别书.json", "txt_file": "39647_诀别书_简谱.txt", "download_time": "2026-09-17 03:20:57" }, "39411": { "title": "luvsic和花之舞不能说的秘密_1", "json_file": "39411_luvsic和花之舞不能说的秘密_1.json", "txt_file": "39411_luvsic和花之舞不能说的秘密_1_简谱.txt", "download_time": "2026-09-17 03:22:11" }, "39151": { "title": "夜的钢琴曲Ⅴ", "json_file": "39151_夜的钢琴曲Ⅴ.json", "txt_file": "39151_夜的钢琴曲Ⅴ_简谱.txt", "download_time": "2026-09-17 03:23:28" }, "40310": { "title": "不老梦", "json_file": "40310_不老梦.json", "txt_file": "40310_不老梦_简谱.txt", "download_time": "2026-09-17 03:24:44" }, "40130": { "title": "玫瑰少年", "json_file": "40130_玫瑰少年.json", "txt_file": "40130_玫瑰少年_简谱.txt", "download_time": "2026-09-17 03:25:58" }, "39649": { "title": "Are you lost", "json_file": "39649_Are you lost.json", "txt_file": "39649_Are you lost_简谱.txt", "download_time": "2026-09-17 03:27:12" }, "39278": { "title": "His Theme(三指版)", "json_file": "39278_His Theme(三指版).json", "txt_file": "39278_His Theme(三指版)_简谱.txt", "download_time": "2026-09-17 03:28:26" }, "15117": { "title": "Are You lost4", "json_file": "15117_Are You lost4.json", "txt_file": "15117_Are You lost4_简谱.txt", "download_time": "2026-09-17 03:29:39" }, "40074": { "title": "带我走", "json_file": "40074_带我走.json", "txt_file": "40074_带我走_简谱.txt", "download_time": "2026-09-17 03:30:52" }, "39282": { "title": "Cheap Thrills", "json_file": "39282_Cheap Thrills.json", "txt_file": "39282_Cheap Thrills_简谱.txt", "download_time": "2026-09-17 03:32:10" }, "9020": { "title": "室内系的trackmaker3", "json_file": "9020_室内系的trackmaker3.json", "txt_file": "9020_室内系的trackmaker3_简谱.txt", "download_time": "2026-09-17 03:33:23" } } };

    // 获取持久化存储的已下载索引
    function getIndexData() {
        try {
            const stored = GM_getValue('mgm_downloaded_index_v1');
            if (stored && typeof stored === 'object' && Array.isArray(stored.ids)) {
                return stored;
            }
        } catch (e) { }
        return DEFAULT_INDEX_DATA;
    }

    function saveIndexData(data) {
        try {
            GM_setValue('mgm_downloaded_index_v1', data);
        } catch (e) { }
    }

    let indexData = getIndexData();
    let localServerConnected = false;
    let capturedScore = null;

    // 尝试与本地同步服务 (local_sync.py:18088) 握手
    async function checkLocalServer() {
        try {
            const res = await fetch('http://127.0.0.1:18088/status', { method: 'GET' });
            if (res.ok) {
                const status = await res.json();
                if (status.running) {
                    localServerConnected = true;
                    indexData.ids = status.ids || [];
                    indexData.records = status.records || {};
                    indexData.total_downloaded = status.total_downloaded || 0;
                    saveIndexData(indexData);
                    console.log('[SkyMusic] 🔌 已成功连通本地同步服务 (http://127.0.0.1:18088)，已加载', indexData.total_downloaded, '首本地记录');
                    updateStatusUI();
                    markScoreCardsOnList();
                    return;
                }
            }
        } catch (e) {
            localServerConnected = false;
        }
    }

    // ========================================================
    // 1. 核心逻辑：Hook 浏览器的 WebCrypto AES-GCM 解密
    // ========================================================
    const originalDecrypt = targetWindow.crypto.subtle.decrypt.bind(targetWindow.crypto.subtle);
    targetWindow.crypto.subtle.decrypt = async function (...args) {
        const decryptedBuffer = await originalDecrypt(...args);
        try {
            const text = new TextDecoder('utf-8').decode(decryptedBuffer);
            if (text.includes('"format"') && (text.includes('"mgm.score"') || text.includes('"tracks"'))) {
                const parsed = JSON.parse(text);
                const scoreData = parsed?.data?.score || parsed?.score || parsed;
                if (scoreData?.tracks || scoreData?.notes) {
                    console.log('[SkyMusic] 🎯 成功截获解密乐谱数据:', scoreData);
                    capturedScore = scoreData;
                    onScoreReady();
                }
            }
        } catch (e) { }
        return decryptedBuffer;
    };

    // ========================================================
    // 2. 格式规范化：完全复刻 scores 文件夹内的标准 JSON 格式
    //    包含: success, data.score.format, version, durationMs, noteCount, trackCount, bpm, metadata, timing, range, tracks -> notes
    // ========================================================
    function formatToScoresFolderStandard(rawScore) {
        let score = rawScore;
        if (rawScore && rawScore.data && rawScore.data.score) {
            score = rawScore.data.score;
        } else if (rawScore && rawScore.score) {
            score = rawScore.score;
        }

        const metadata = score.metadata || {};
        let title = metadata.title || score.title || '';
        if (!title) {
            const h1 = document.querySelector('h1');
            title = h1 ? h1.innerText.trim() : '光遇乐谱';
        }
        const bpm = score.bpm || 120;
        const tracks = score.tracks || [];

        const cleanTracks = tracks.map((t, tIdx) => {
            const rawNotes = t.notes || [];
            const notes = rawNotes.map((n, nIdx) => {
                const startMs = n.startMs ?? n.time ?? n.timeMs ?? 0;
                let pitch = n.pitch;
                let keyIdx = n.keyIndex;
                let rawKey = n.rawKey;

                if (rawKey && typeof rawKey === 'string' && rawKey.includes('Key')) {
                    const m = rawKey.match(/Key(\d+)/i);
                    if (m) {
                        const k0 = parseInt(m[1], 10);
                        if (pitch == null) pitch = k0 + 1;
                        if (keyIdx == null) keyIdx = k0 + 1;
                    }
                }
                if (keyIdx == null && pitch != null) keyIdx = pitch;
                if (pitch == null && keyIdx != null) pitch = keyIdx;
                if (pitch == null) pitch = 1;
                if (keyIdx == null) keyIdx = 1;

                if (!rawKey) rawKey = `1Key${keyIdx - 1}`;
                const targetKey = `sky.key.${keyIdx}`;

                return {
                    id: n.id || `t${tIdx + 1}_n${nIdx + 1}`,
                    startMs: startMs,
                    durationMs: n.durationMs ?? 0,
                    pitch: pitch,
                    keyIndex: keyIdx,
                    velocity: n.velocity ?? 100,
                    rawKey: rawKey,
                    targetKey: targetKey
                };
            });

            notes.sort((a, b) => a.startMs - b.startMs);

            return {
                id: t.id || `track_${tIdx + 1}`,
                name: t.name || `Sky 轨道 ${tIdx + 1}`,
                instrument: t.instrument || 'sky_piano',
                muted: !!t.muted,
                solo: !!t.solo,
                preview: t.preview || {
                    defaultInstrument: 'sky_piano',
                    metronome: false,
                    countInBeats: 0
                },
                notes: notes
            };
        });

        let totalNotes = 0;
        let maxMs = 0;
        cleanTracks.forEach(tr => {
            totalNotes += tr.notes.length;
            tr.notes.forEach(nt => {
                if (nt.startMs > maxMs) maxMs = nt.startMs;
            });
        });

        const cleanScore = {
            format: score.format || 'mgm.score',
            version: score.version || 1,
            durationMs: score.durationMs || maxMs,
            noteCount: score.noteCount || totalNotes,
            trackCount: cleanTracks.length,
            bpm: bpm,
            metadata: {
                title: title,
                artist: metadata.artist || score.artist || '网络',
                creator: metadata.creator || score.creator || '网络',
                description: metadata.description || '',
                sourceFormat: metadata.sourceFormat || 'sky-studio-json'
            },
            timing: score.timing || {
                timeBase: 'milliseconds',
                bpm: bpm,
                offsetMs: 0
            },
            range: score.range || {
                code: '15',
                keyCount: 15
            },
            preview: score.preview || {
                defaultInstrument: 'sky_piano',
                metronome: false,
                countInBeats: 0
            },
            target: score.target || {
                platform: 'android',
                game: 'sky',
                layoutProfileId: '',
                clickMode: 'accessibility'
            },
            tracks: cleanTracks
        };

        return {
            success: true,
            data: {
                score: cleanScore
            }
        };
    }

    // 用于快捷复制到光遇自动弹琴脚本的简易格式
    function convertToSkyStudioClipboard(scoreObj) {
        const score = scoreObj.data?.score || scoreObj;
        const title = score.metadata?.title || score.title || '光遇乐谱';
        const bpm = score.bpm || 120;
        const tracks = score.tracks || [];

        const songNotes = [];
        for (const t of tracks) {
            const tname = String(t.name || '').toLowerCase();
            const tinst = String(t.instrument || '').toLowerCase();
            const isPercussion = ['drum', 'tr_909', 'sfx', 'percussion', '鼓', '打击乐'].some(p => tname.includes(p) || tinst.includes(p));
            if (isPercussion && tracks.length > 1) continue;

            for (const n of (t.notes || [])) {
                const timeMs = n.startMs ?? 0;
                let keyIdx = n.keyIndex ? n.keyIndex - 1 : (n.pitch ? n.pitch - 1 : -1);
                if (n.rawKey && n.rawKey.includes('Key')) {
                    const m = n.rawKey.match(/Key(\d+)/i);
                    if (m) keyIdx = parseInt(m[1], 10);
                }
                if (keyIdx >= 0 && keyIdx <= 14) {
                    songNotes.push({
                        time: timeMs,
                        key: `1Key${keyIdx}`
                    });
                }
            }
        }

        songNotes.sort((a, b) => a.time - b.time);

        return JSON.stringify([
            {
                name: title,
                bpm: bpm,
                bitsPerPage: 16,
                pitchLevel: 0,
                songNotes: songNotes
            }
        ], null, 2);
    }

    function getCurrentScoreId() {
        const m = location.pathname.match(/\/scores\/(\d+)/);
        return m ? parseInt(m[1], 10) : null;
    }

    function isScoreDownloaded(sid) {
        if (!sid) return false;
        return indexData.ids.includes(sid) || !!indexData.records[String(sid)];
    }

    function recordDownloaded(sid, title, filename) {
        if (!sid) return;
        const nowStr = new Date().toISOString().replace('T', ' ').slice(0, 19);
        const idSet = new Set(indexData.ids);
        idSet.add(sid);
        indexData.ids = Array.from(idSet).sort((a, b) => a - b);
        indexData.total_downloaded = indexData.ids.length;
        indexData.last_updated = nowStr;
        indexData.records = indexData.records || {};
        indexData.records[String(sid)] = {
            title: title,
            json_file: filename,
            txt_file: `${sid}_${title}_简谱.txt`,
            download_time: nowStr
        };
        saveIndexData(indexData);
        updateStatusUI();
        markScoreCardsOnList();
    }

    // ========================================================
    // 3. 乐谱列表页 (/scores) 自动标记 [已下载]
    // ========================================================
    function markScoreCardsOnList() {
        const links = document.querySelectorAll('a[href*="/scores/"]');
        links.forEach(a => {
            const m = a.getAttribute('href').match(/\/scores\/(\d+)/);
            if (!m) return;
            const sid = parseInt(m[1], 10);
            if (isScoreDownloaded(sid)) {
                if (!a.querySelector('.sky-downloaded-tag')) {
                    const tag = document.createElement('span');
                    tag.className = 'sky-downloaded-tag';
                    tag.innerText = '✓已下载';
                    tag.style.cssText = 'position:absolute;top:6px;right:6px;background:#10b981;color:#fff;font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;z-index:10;box-shadow:0 2px 6px rgba(0,0,0,0.3);pointer-events:none;';
                    if (getComputedStyle(a).position === 'static') {
                        a.style.position = 'relative';
                    }
                    a.appendChild(tag);
                }
            }
        });
    }

    // ========================================================
    // 4. UI 悬浮面板：状态识别、复制、下载与索引维护
    // ========================================================
    function initUI() {
        if (document.getElementById('skymusic-exporter-root')) return;

        const panel = document.createElement('div');
        panel.id = 'skymusic-exporter-root';
        panel.innerHTML = `
            <style>
                #skymusic-exporter-root {
                    position: fixed;
                    bottom: 24px;
                    right: 24px;
                    z-index: 999999;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                }
                .sky-export-card {
                    background: rgba(15, 20, 32, 0.95);
                    backdrop-filter: blur(14px);
                    -webkit-backdrop-filter: blur(14px);
                    border: 1px solid rgba(255, 255, 255, 0.16);
                    border-radius: 12px;
                    padding: 12px 16px;
                    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
                    color: #fff;
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                    min-width: 300px;
                }
                .sky-card-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 8px;
                }
                .sky-header-left {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                .sky-status-dot {
                    width: 10px;
                    height: 10px;
                    border-radius: 50%;
                    background: #f59e0b;
                    box-shadow: 0 0 8px #f59e0b;
                    flex-shrink: 0;
                }
                .sky-status-dot.ready {
                    background: #10b981;
                    box-shadow: 0 0 10px #10b981;
                }
                .sky-badge {
                    font-size: 11px;
                    padding: 2px 7px;
                    border-radius: 4px;
                    font-weight: 700;
                    letter-spacing: 0.3px;
                }
                .sky-badge.downloaded {
                    background: rgba(16, 185, 129, 0.2);
                    color: #10b981;
                    border: 1px solid rgba(16, 185, 129, 0.4);
                }
                .sky-badge.not-downloaded {
                    background: rgba(245, 158, 11, 0.15);
                    color: #f59e0b;
                    border: 1px solid rgba(245, 158, 11, 0.3);
                }
                .sky-server-badge {
                    font-size: 10px;
                    color: #64748b;
                }
                .sky-server-badge.online {
                    color: #38bdf8;
                }
                .sky-title-area {
                    display: flex;
                    flex-direction: column;
                }
                .sky-title-area strong {
                    font-size: 13px;
                    color: #e2e8f0;
                }
                .sky-title-area span {
                    font-size: 11px;
                    color: #94a3b8;
                }
                .sky-btn-group {
                    display: flex;
                    gap: 8px;
                }
                .sky-btn {
                    border: none;
                    outline: none;
                    cursor: pointer;
                    padding: 7px 12px;
                    border-radius: 6px;
                    font-size: 12px;
                    font-weight: 600;
                    transition: all 0.2s;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 4px;
                    flex: 1;
                }
                .sky-btn-copy { background: #3b82f6; color: #fff; }
                .sky-btn-copy:hover { background: #2563eb; }
                .sky-btn-dl { background: #10b981; color: #fff; }
                .sky-btn-dl:hover { background: #059669; }
                .sky-btn:disabled { opacity: 0.35; cursor: not-allowed; }
                .sky-extra-bar {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    border-top: 1px solid rgba(255, 255, 255, 0.08);
                    padding-top: 6px;
                    margin-top: 2px;
                    font-size: 10px;
                    color: #64748b;
                }
                .sky-link-btn {
                    color: #94a3b8;
                    text-decoration: underline;
                    cursor: pointer;
                    background: none;
                    border: none;
                    padding: 0;
                    font-size: 10px;
                }
                .sky-link-btn:hover { color: #e2e8f0; }
                .sky-toast {
                    position: absolute;
                    top: -42px;
                    left: 50%;
                    transform: translateX(-50%);
                    background: #10b981;
                    color: #fff;
                    padding: 6px 14px;
                    border-radius: 6px;
                    font-size: 12px;
                    white-space: nowrap;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                    opacity: 0;
                    pointer-events: none;
                    transition: opacity 0.25s;
                }
                .sky-toast.show { opacity: 1; }
            </style>
            <div class="sky-export-card">
                <div class="sky-toast" id="sky-toast">已复制！</div>
                <div class="sky-card-header">
                    <div class="sky-header-left">
                        <div class="sky-status-dot" id="sky-dot"></div>
                        <strong id="sky-label" style="font-size:13px;">光遇琴谱</strong>
                        <span class="sky-badge" id="sky-download-badge">检测中...</span>
                    </div>
                    <span class="sky-server-badge" id="sky-server-status" title="运行 python local_sync.py 可直接写入本地 scores 目录">本地直连: 检测中</span>
                </div>
                <div class="sky-title-area">
                    <span id="sky-sub">等待乐谱加载...</span>
                    <span id="sky-record-detail" style="color:#64748b;font-size:10px;margin-top:2px;"></span>
                </div>
                <div class="sky-btn-group">
                    <button class="sky-btn sky-btn-copy" id="sky-btn-copy" disabled title="复制为可直接粘贴至光遇弹琴脚本的标准格式">📋 复制弹琴JSON</button>
                    <button class="sky-btn sky-btn-dl" id="sky-btn-dl" disabled title="下载与 scores 文件夹内完全一致的 JSON 格式">⬇️ 保存原格式JSON</button>
                </div>
                <div class="sky-extra-bar">
                    <span>已收录: <b id="sky-total-count" style="color:#e2e8f0;">0</b> 首</span>
                    <div style="display:flex;gap:8px;">
                        <button class="sky-link-btn" id="sky-btn-export-index" title="下载最新维护好的 downloaded_ids.json">💾 导出Index</button>
                        <button class="sky-link-btn" id="sky-btn-import-index" title="从磁盘选择已有 downloaded_ids.json 同步">📂 导入Index</button>
                    </div>
                </div>
            </div>
            <input type="file" id="sky-file-input" accept=".json" style="display:none;" />
        `;
        document.body.appendChild(panel);

        // 复制按钮：复制光遇 Sky Studio 规范的轻量弹琴数组
        document.getElementById('sky-btn-copy').onclick = () => {
            if (!capturedScore) return;
            const standardObj = formatToScoresFolderStandard(capturedScore);
            const clipboardText = convertToSkyStudioClipboard(standardObj);
            if (typeof GM_setClipboard !== 'undefined') {
                GM_setClipboard(clipboardText);
            } else {
                navigator.clipboard.writeText(clipboardText);
            }
            showToast('已复制光遇弹琴 JSON！');
        };

        // 下载按钮：保存与 scores 文件夹内格式完全一致的标准 JSON
        document.getElementById('sky-btn-dl').onclick = async () => {
            if (!capturedScore) return;
            const sid = getCurrentScoreId();
            const standardObj = formatToScoresFolderStandard(capturedScore);
            const scoreData = standardObj.data.score;
            const title = scoreData.metadata.title;
            const safeTitle = title.replace(/[\\/:*?"<>|\r\n\t]/g, '_').trim() || `score_${sid}`;
            const filename = `${sid}_${safeTitle}.json`;
            const jsonText = JSON.stringify(standardObj, null, 2);

            // 优先通过本地 Python 同步服务直接写盘
            if (localServerConnected) {
                try {
                    const res = await fetch('http://127.0.0.1:18088/save', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            id: sid,
                            title: safeTitle,
                            content: standardObj
                        })
                    });
                    const ret = await res.json();
                    if (ret.success) {
                        recordDownloaded(sid, safeTitle, filename);
                        showToast(`已存入 scores 目录并生成简谱！`);
                        return;
                    }
                } catch (e) {
                    console.warn('[SkyMusic] 本地服务保存失败，回退浏览器下载:', e);
                }
            }

            // 回退方案：浏览器常规下载并更新内置索引
            const blob = new Blob([jsonText], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);

            recordDownloaded(sid, safeTitle, filename);
            showToast(`已下载，并已维护到下载索引！`);
        };

        // 导出最新 downloaded_ids.json
        document.getElementById('sky-btn-export-index').onclick = () => {
            const blob = new Blob([JSON.stringify(indexData, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'downloaded_ids.json';
            a.click();
            URL.revokeObjectURL(url);
            showToast('已导出最新 downloaded_ids.json！');
        };

        // 导入已有 downloaded_ids.json
        const fileInput = document.getElementById('sky-file-input');
        document.getElementById('sky-btn-import-index').onclick = () => fileInput.click();
        fileInput.onchange = (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (event) => {
                try {
                    const imported = JSON.parse(event.target.result);
                    if (imported && Array.isArray(imported.ids)) {
                        indexData = imported;
                        saveIndexData(indexData);
                        updateStatusUI();
                        markScoreCardsOnList();
                        showToast(`成功导入！包含 ${imported.ids.length} 首已下载记录`);
                    } else {
                        alert('文件格式不正确，缺少 ids 数组！');
                    }
                } catch (err) {
                    alert('解析 JSON 失败: ' + err.message);
                }
            };
            reader.readAsText(file);
        };

        updateStatusUI();
    }

    function showToast(msg) {
        const toast = document.getElementById('sky-toast');
        if (!toast) return;
        toast.innerText = msg;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 2200);
    }

    function updateStatusUI() {
        const sid = getCurrentScoreId();
        const badge = document.getElementById('sky-download-badge');
        const detail = document.getElementById('sky-record-detail');
        const serverStatus = document.getElementById('sky-server-status');
        const totalCount = document.getElementById('sky-total-count');

        if (totalCount) totalCount.innerText = indexData.total_downloaded || indexData.ids.length || 0;

        if (serverStatus) {
            if (localServerConnected) {
                serverStatus.innerText = '本地直连: 在线 ✓';
                serverStatus.classList.add('online');
            } else {
                serverStatus.innerText = '纯浏览器模式';
                serverStatus.classList.remove('online');
            }
        }

        if (badge && sid) {
            const downloaded = isScoreDownloaded(sid);
            if (downloaded) {
                badge.innerText = '✓ 本地已下载';
                badge.className = 'sky-badge downloaded';
                const rec = indexData.records ? indexData.records[String(sid)] : null;
                if (rec && detail) {
                    detail.innerText = `下载时间: ${rec.download_time || '已记录'} (${rec.json_file || ''})`;
                }
            } else {
                badge.innerText = '⏳ 本地未下载';
                badge.className = 'sky-badge not-downloaded';
                if (detail) detail.innerText = '本地记录中暂无此曲';
            }
        } else if (badge) {
            badge.innerText = '列表浏览中';
            badge.className = 'sky-badge not-downloaded';
        }
    }

    function onScoreReady() {
        const dot = document.getElementById('sky-dot');
        const sub = document.getElementById('sky-sub');
        const btnCopy = document.getElementById('sky-btn-copy');
        const btnDl = document.getElementById('sky-btn-dl');
        if (!dot || !sub || !btnCopy || !btnDl) return;

        const standard = formatToScoresFolderStandard(capturedScore);
        const score = standard.data.score;
        dot.classList.add('ready');
        sub.innerText = `已就绪 (${score.noteCount} 个音符 / ${score.bpm} BPM)`;
        btnCopy.disabled = false;
        btnDl.disabled = false;

        const sid = getCurrentScoreId();
        if (isScoreDownloaded(sid)) {
            btnDl.innerText = '⬇️ 重新保存覆盖';
        } else {
            btnDl.innerText = '⬇️ 保存原格式JSON';
        }
    }

    function startup() {
        initUI();
        checkLocalServer();
        setInterval(markScoreCardsOnList, 1500);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startup);
    } else {
        startup();
    }
})();
