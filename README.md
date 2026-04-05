# Woolf Reader Agent

实体阅读设备的 AI 后端 + 前端界面。读者通过摇杆选中文本片段，Virginia Woolf AI 即时回应，提供文学解读。支持 ESP32-S3 硬件设备，也提供浏览器键盘演示模式。

---

## 系统架构

```
ESP32-S3 (摇杆 + 麦克风)
    │ USB CDC Serial (JSON 事件)
    ▼
浏览器前端 (Web Serial API)  ←→  recommendation-agent（手机约书 → 阅读器接续）
    │ HTTP / SSE
    ▼
FastAPI 后端 (port 8001)
    │ Zhipu AI (glm-4.5 / glm-4.5-air)
    ▼
ChromaDB 向量库（本地）
```

---

## 目录结构

```
reader-agent/
├── agent/
│   ├── agent.py            # WoolfAgent：场景路由 + ReAct 流式对话
│   ├── persona.py          # 人设构建 + 反漂移摘要
│   ├── scenarios.py        # 场景检测（DISCOVERY / ANNOTATION / THEMATIC / REACT）
│   ├── dialogue_state.py   # 5 轮探索对话状态机
│   └── tools.py            # RAG 工具（OpenAI function calling 格式）
├── api/
│   ├── main.py             # FastAPI 入口
│   ├── reader_router.py    # 阅读器端点（/reader/*）
│   ├── mobile_router.py    # 移动端端点（/mobile/*）
│   └── notes_router.py     # 笔记端点（/notes/*）
├── data/
│   ├── persona_anchors.json    # 伍尔夫人设锚点 + 5 轮探索问题
│   └── raw/                    # 书本文本（UTF-16 中文 + UTF-8 英文）
├── scripts/
│   └── ingest_works.py         # 向量库灌入脚本
├── firmware/               # ESP32-S3 固件（ESP-IDF）
├── frontend/               # React + Vite 阅读器界面
├── requirements.txt
├── setup_kb.sh             # 一键建库脚本
└── .env.example
```

---

## 快速开始（新电脑）

### 前置条件

- Python 3.10+
- Node.js 18+
- [智谱 AI](https://open.bigmodel.cn) API Key

### 步骤 1：后端安装

```bash
cd reader-agent

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# 用文本编辑器打开 .env，填入 ZHIPU_API_KEY
```

### 步骤 2：构建知识库（首次，约 5-10 分钟）

```bash
bash setup_kb.sh
```

> 会自动下载 sentence-transformers 嵌入模型（~90MB），把 `data/raw/` 的书本向量化写入 ChromaDB。

### 步骤 3：启动后端

```bash
python -m uvicorn api.main:app --port=8001 --reload
```

访问 `http://localhost:8001/docs` 确认正常。

### 步骤 4：启动前端

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`，点击"演示模式（键盘）"体验完整流程。

---

## 键盘演示模式

| 按键 | 功能 |
|------|------|
| ↑ / ↓ | 移动光标（逐句） |
| Space / Enter | 开始选中；再按一次确认，弹出 AI 对话 |
| W | 唤醒：对当前句子直接提问 |
| Esc | 取消选中 / 关闭对话 |

AgentUI 打开后可鼠标点击问题，或"✎ 自己提问"输入自定义问题。

---

## API 端点

### 阅读器端 `/reader/*`

| 端点 | 方法 | 说明 |
|------|------|------|
| `/reader/text?book=daluo_weifuren` | GET | 获取书本段落列表 |
| `/reader/suggest` | POST | 为选中段落即时生成 3 个建议问题 |
| `/reader/chat` | POST | 对选中段落提问（SSE 流式） |
| `/reader/ws` | WebSocket | 实时对话（硬件设备用） |
| `/reader/annotated_paragraphs/{session_id}` | GET | 有主动标注的段落索引 |
| `/reader/proactive/{session_id}/{para_idx}` | GET | 预生成的主动解读 |

### 移动端 `/mobile/*`（与推荐 App 联动）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/mobile/set_book` | POST | 手机约定书目，同步给阅读器 |
| `/mobile/scheduled_book` | GET | 阅读器启动时拉取约定书目 |
| `/mobile/chat` | POST | 单轮对话 |
| `/mobile/ws` | WebSocket | 流式对话 |

### 支持书目

| slug | 书名 |
|------|------|
| `daluo_weifuren` | 达洛维夫人（中文，默认） |
| `yijian_fangjian` | 一间只属于自己的房间（中文） |
| `xie_xialai` | 写下来，痛苦就会过去（中文） |
| `sikao_dikang` | 思考就是我的抵抗（中文） |
| `mrs_dalloway` | Mrs Dalloway（英文） |
| `a_room_of_ones_own` | A Room of One's Own（英文） |

---

## 硬件集成（ESP32-S3）

### 所需硬件

- ESP32-S3 开发板
- 双轴摇杆 × 2（带按键，KY-023 或同类）
- I2S 数字麦克风（INMP441 或同类）
- USB 数据线（USB CDC 通信）

### 接线

| 信号 | ESP32-S3 GPIO |
|------|--------------|
| 右摇杆 Y 轴 | GPIO1 (ADC1_CH0) |
| 左摇杆 Y 轴 | GPIO4 (ADC1_CH3) |
| 右摇杆按键（确认） | GPIO3 |
| 左摇杆按键（取消） | GPIO6 |
| 麦克风 CLK (BCLK) | GPIO7 |
| 麦克风 WS (LRCLK) | GPIO8 |
| 麦克风 DATA | GPIO9 |

**修改接线**：打开 `firmware/main/main.c`，修改顶部宏定义：

```c
#define RIGHT_JOY_Y_CH    ADC_CHANNEL_0    // 右摇杆 Y 轴
#define LEFT_JOY_Y_CH     ADC_CHANNEL_3    // 左摇杆 Y 轴
#define RIGHT_BTN_PIN     GPIO_NUM_3       // 确认按键
#define LEFT_BTN_PIN      GPIO_NUM_6       // 取消按键
#define I2S_CLK_PIN       GPIO_NUM_7
#define I2S_WS_PIN        GPIO_NUM_8
#define I2S_DATA_PIN      GPIO_NUM_9
```

### 固件烧录

需要 [ESP-IDF v5.x](https://docs.espressif.com/projects/esp-idf/zh_CN/latest/esp32s3/get-started/)：

```bash
cd firmware

idf.py set-target esp32s3
idf.py build

# 替换 /dev/tty.usbmodem* 为实际串口
idf.py -p /dev/tty.usbmodem* flash monitor
```

### 固件事件格式

固件通过 USB CDC Serial 发送 JSON 行，前端通过 Web Serial API 接收：

```json
{"event":"cursor","value":"up"}
{"event":"cursor","value":"down"}
{"event":"action","value":""}
{"event":"cancel","value":""}
{"event":"wake","value":"woolf"}
```

### 替换为其他通信方式

只需修改 `frontend/src/hooks/useSerial.js`，将其他信号源（MQTT、WebSocket、蓝牙等）转换为上述事件格式即可，前端其余代码无需改动。

---

## 定制伍尔夫人设

编辑 `data/persona_anchors.json`：

```json
{
  "identity": "核心身份描述",
  "voice_anchors": ["语气规则1", "语气规则2"],
  "forbidden_phrases": ["禁止出现的说法"],
  "discovery_questions": [
    { "round": 1, "theme": "LLM 用来生成第1轮问题的话题指引" },
    ...
    { "round": 5, "synthesis": true, "instruction": "第5轮综合推荐指令" }
  ]
}
```

> `theme` 是传给 LLM 的话题指引，不直接显示给用户——LLM 会生成符合伍尔夫语气的自然问句。

---

## 环境变量

```env
ZHIPU_API_KEY=          # 必填
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
ZHIPU_MODEL_FAST=glm-4.5-air   # 建议问题、段落标注（较快）
ZHIPU_MODEL_MAIN=glm-4.5       # 主对话（较强）

CHROMA_DB_PATH=./kb/chroma
EMBEDDING_MODEL=all-MiniLM-L6-v2
```
