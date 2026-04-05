# ESP32-S3 × Web App 硬件软件联调全链路

> 日期：2026-04-05
> 项目：Woolf Reader Agent（圆筒阅读器）
> 标签：#ESP32-S3 #WebSerial #硬件联调 #FastAPI #React #WakeNet

---

## 一、系统整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    物理设备层                             │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐                  │
│  │  右摇杆(ADC) │    │  左摇杆(ADC) │                  │
│  │  右摇杆按键  │    │  左摇杆按键  │                  │
│  └──────┬───────┘    └──────┬───────┘                  │
│         │                   │                           │
│         ▼                   ▼                           │
│  ┌─────────────────────────────────┐                   │
│  │         ESP32-S3（主控）         │                   │
│  │  - ADC 读摇杆模拟信号            │                   │
│  │  - GPIO 读按键数字信号           │                   │
│  │  - I2S 读麦克风音频流            │                   │
│  │  - WakeNet 本地唤醒词检测        │                   │
│  │  - USB CDC 发 JSON 事件         │                   │
│  └──────────────┬──────────────────┘                   │
│                 │ USB Cable                             │
└─────────────────┼───────────────────────────────────────┘
                  │
┌─────────────────┼───────────────────────────────────────┐
│                 ▼           电脑层                        │
│  ┌──────────────────────────────────────────────────┐   │
│  │              React 前端（浏览器）                  │   │
│  │                                                  │   │
│  │  Web Serial API ──读串口──► useSerial hook       │   │
│  │                                  │               │   │
│  │                                  ▼               │   │
│  │                           事件分发 (App.jsx)      │   │
│  │                                  │               │   │
│  │                    ┌─────────────┼─────────────┐ │   │
│  │                    ▼             ▼             ▼ │   │
│  │             ConnectScreen  ReaderScreen   AgentUI│   │
│  │                                  │               │   │
│  │                          HTTP fetch              │   │
│  └──────────────────────────────────┼───────────────┘   │
│                                     │                    │
│  ┌──────────────────────────────────┼───────────────┐   │
│  │              FastAPI 后端         ▼               │   │
│  │                                                  │   │
│  │  /reader/text          → 返回正文段落列表          │   │
│  │  /reader/suggest       → 生成 3 个建议问题        │   │
│  │  /reader/chat          → Agent 回复（4场景）      │   │
│  │  /reader/proactive     → 主动气泡内容             │   │
│  │  /reader/annotated_paragraphs → 有标注段落 ID     │   │
│  │  /notes/add            → 保存用户笔记             │   │
│  │                                                  │   │
│  │  ┌────────────┐  ┌───────────┐  ┌────────────┐  │   │
│  │  │  ChromaDB  │  │ NetworkX  │  │  Claude API│  │   │
│  │  │ (7个collection)│  │  (主题图) │  │ (Agent)   │  │   │
│  │  └────────────┘  └───────────┘  └────────────┘  │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │         HDMI 显示屏（2400×1080 / 69.5×36.1mm）    │   │
│  │         逻辑分辨率 600×270（4x CSS 缩放）          │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 二、ESP32-S3 固件层

### 2.1 为什么选 ESP32-S3

| 特性 | 说明 |
|------|------|
| 原生 USB | 内置 USB-OTG，可直接做 USB CDC Serial，无需额外 CH340/CP2102 芯片 |
| 双核 LX7 | 音频处理（核心1）+ 摇杆轮询（核心0）不互相阻塞 |
| 向量指令 | 支持 SIMD，WakeNet 神经网络推理可在本地跑 |
| 丰富 ADC | 20 个 ADC 通道，够接多个摇杆轴 |
| I2S 接口 | 支持 MEMS 麦克风标准协议 |

### 2.2 摇杆 → ADC → 事件

**摇杆本质**：一个可变电阻（电位器）。推动摇杆时，电阻值改变，分压后输出 0~3.3V 的模拟电压。

```
摇杆机械运动
  → 电位器阻值变化
  → 分压电路输出 0~3.3V 模拟电压
  → ESP32-S3 ADC 量化为 0~4095 的整数
  → 固件判断方向（与中位 2048 比较）
  → 发 JSON 事件到串口
```

**关键参数**：
- `JOY_CENTER = 2048`：摇杆静止时的 ADC 值（12-bit 中点）
- `JOY_DEADZONE = 500`：死区，避免摇杆轻微抖动误触发
- `MOVE_INTERVAL_MS = 150`：持续拨动时重复发事件的间隔

**代码核心逻辑**：
```c
// 右摇杆上推（ADC 值 < 中位 - 死区）→ cursor up
if (r_y < JOY_CENTER - JOY_DEADZONE) r_dir = DIR_UP;
// 右摇杆下推（ADC 值 > 中位 + 死区）→ cursor down
if (r_y > JOY_CENTER + JOY_DEADZONE) r_dir = DIR_DOWN;
```

**为什么需要死区**：摇杆中位不是精确的 2048，有机械误差（±200 左右），不加死区会持续误触发。

### 2.3 按键 → GPIO → 事件

按键接法：一端接 GPIO，另一端接 GND，ESP32-S3 内部上拉（`GPIO_PULLUP_ENABLE`）。

```
按键松开：GPIO → 内部上拉 → 3.3V → gpio_get_level() = 1
按键按下：GPIO → 直接接 GND → 0V  → gpio_get_level() = 0
```

**边沿检测**：固件记录上次状态 `last_btn`，检测到 `btn=0 && last_btn=1` 时发事件（只在按下瞬间触发一次，不持续触发）。

### 2.4 麦克风 → I2S → WakeNet

**I2S 是什么**：Inter-IC Sound，芯片间传输数字音频的标准协议，3 根线：
- `BCLK`（位时钟）：每个 bit 一个脉冲
- `WS/LRCLK`（字选择）：区分左右声道
- `DATA`（数据）：串行音频数据

**INMP441 麦克风**：输出左对齐 32-bit 数据，有效音频在高 16-bit：
```c
// 32-bit 采样取高 16-bit，得到标准 PCM
pcm[i] = (int16_t)(raw[i] >> 16);
```

**WakeNet 推理流程**：
```
I2S 读 512 个采样（约 32ms @ 16kHz）
  → 取高 16-bit，得到 512 个 int16_t PCM
  → wn->detect(wnmd, pcm) 推理
  → 返回 > 0 → 检测到唤醒词
  → 发 wake 事件 → 静默 1.5s 防抖
```

**为什么 512 采样**：WakeNet 神经网络固定每次处理 512 个采样（约 32ms），是模型训练时的参数。

### 2.5 串口通信协议

固件与电脑之间通过 USB CDC Serial 传输，协议极简：

```
每行一个 JSON 对象，\n 结尾
{"event":"cursor","value":"up"}
{"event":"cursor","value":"down"}
{"event":"select","value":"expand"}
{"event":"action","value":""}
{"event":"cancel","value":""}
{"event":"wake","value":"woolf"}
```

**为什么用 JSON 而不用原始字节**：调试方便，直接在串口监视器里能看懂；前端解析简单；格式扩展容易。

---

## 三、Web Serial API（浏览器层）

### 3.1 是什么

W3C 标准 API，允许浏览器直接读写 USB 串口设备，无需安装驱动或中间件。

**支持的浏览器**：Chrome 89+、Edge 89+（Safari / Firefox 不支持）

### 3.2 权限模型

浏览器出于安全要求用户**主动授权**：
- `navigator.serial.requestPort()` 必须在用户点击事件处理函数里调用
- 弹出系统对话框，用户选择串口设备
- 授权后，同一来源（origin）下次打开可用 `navigator.serial.getPorts()` 自动获取已授权端口（无需再次弹框）

### 3.3 读取流程

```javascript
// 1. 用户点击按钮 → 弹出设备选择框
const port = await navigator.serial.requestPort()

// 2. 打开串口（波特率必须和固件一致）
await port.open({ baudRate: 115200 })

// 3. 持续读取（ReadableStream）
const reader = port.readable.getReader()
while (true) {
    const { value, done } = await reader.read()
    // value 是 Uint8Array（原始字节）
    // 用 TextDecoder 转字符串
    buffer += new TextDecoder().decode(value)
    // 按换行符切割，解析每行 JSON
}
```

**关键细节**：
- `read()` 不保证每次读到完整的一行，需要 buffer 拼接后再按 `\n` 切割
- 固件的 `fflush(stdout)` 很重要，否则数据留在固件缓冲区不发出来

---

## 四、前端架构（React）

### 4.1 显示屏缩放方案

物理屏：2400×1080px，尺寸 69.5×36.1mm → **876 PPI**

设计尺寸：600×270px（逻辑像素）
缩放方式：CSS `transform: scale(4)` + `transform-origin: top left`

```css
#root {
    width: 600px;
    height: 270px;
    transform: scale(4);
    transform-origin: top left;
}
```

**为什么不用 viewport meta**：`<meta name="viewport">` 只对移动端浏览器生效，桌面 Chrome 忽略它。CSS transform 是最可靠的桌面缩放方案。

### 4.2 状态机设计

```
App 层：
  mode: 'connect' | 'reading'

ReaderScreen 层：
  selecting: boolean        ← 是否在选文模式
  cursorLine: number        ← 当前光标段落
  selStart / selEnd: number ← 选中范围
  agentUI: object | null    ← Agent UI 数据（有值则显示叠加层）
  proactiveBubble: object   ← 主动气泡数据
```

**串口事件 → 状态转换**：

```
cursor up/down  →  cursorLine ± 1
select expand   →  selEnd + 1（仅在 selecting=true 时）
action          →  if !selecting: 进入选文模式
                   if selecting:  确认 → 调 /reader/suggest
cancel          →  退出选文模式
wake            →  用当前段落调 /reader/suggest
```

### 4.3 事件订阅模式

`useSerial` hook 在 App 层运行，负责串口读取。`ReaderScreen` 在组件层运行，需要接收事件。

解决方案：**ref 回调模式**（避免跨层 prop drilling）：

```javascript
// App.jsx
const listenerRef = useRef(null)
const onSerialEvent = (fn) => {
    listenerRef.current = fn
    return () => { listenerRef.current = null }  // cleanup
}

// ReaderScreen.jsx
useEffect(() => {
    const unsub = onSerialEvent((event) => { /* 处理事件 */ })
    return unsub  // 组件卸载时自动注销
}, [依赖项])
```

---

## 五、后端 API 设计

### 5.1 端点清单

| 端点 | 方法 | 作用 | 调用时机 |
|------|------|------|---------|
| `/reader/text` | GET | 返回正文段落数组 | 前端初始化时调一次 |
| `/reader/suggest` | POST | 给定段落，返回 3 个建议问题 | 长按选文 or 语音唤醒后 |
| `/reader/chat` | POST | Agent 完整回复（4场景） | 用户选择问题后 |
| `/reader/proactive/{id}/{idx}` | GET | 获取预生成的主动解读 | 前端轮询有标注段落 |
| `/reader/annotated_paragraphs/{id}` | GET | 返回有标注的段落索引列表 | 前端初始化时调一次 |
| `/notes/add` | POST | 保存用户笔记到 ChromaDB | 用户选"加入笔记" |

### 5.2 检索管道（4步）

```
用户问题
  ↓
Step 1: Step-back 扩展
  表面问题 → 2-3 个深层查询（Haiku）

  ↓
Step 2: 向量检索
  多查询 × 多 collection → 并行检索 → 去重候选集

  ↓
Step 3: GraphRAG 扩展
  top-3 结果 → 在 NetworkX 主题图里找主题相连邻居 → 扩大候选集

  ↓
Step 4: MMR 重排序
  相关性 × 多样性（λ=0.6）→ 最终 top-k 结果
```

### 5.3 4 个场景的路由逻辑

```python
# scenarios.py 判断优先级
1. is_new session          → DISCOVERY（5轮探究状态机）
2. highlighted_passage     → ANNOTATION（单次RAG直接注释）
3. thematic 信号词         → THEMATIC（Plan-and-Execute）
4. 其他                    → REACT（标准ReAct工具循环）
```

---

## 六、未完成工作清单

### 后端（3项）

#### 1. `/reader/suggest` 端点
**位置**：`api/reader_router.py`
**功能**：接收选中段落，调 Claude 生成 3 个建议问题
**代码**：
```python
class SuggestRequest(BaseModel):
    session_id: str
    passage: str

@router.post("/suggest")
async def suggest_questions(req: SuggestRequest):
    agent = _get_or_create_agent(req.session_id)
    system = build_system_prompt(req.session_id, "reader")
    resp = await asyncio.to_thread(
        agent.client.messages.create,
        model=MODEL,
        max_tokens=300,
        system=system,
        messages=[{"role": "user", "content":
            f'A reader selected: "{req.passage}"\n'
            'Generate 3 questions they might ask. Output JSON array only: ["Q1","Q2","Q3"]'
        }]
    )
    import json
    questions = json.loads(resp.content[0].text.strip())
    return {"passage": req.passage, "questions": questions}
```

#### 2. `/reader/annotated_paragraphs` 端点
**位置**：`api/reader_router.py`
**功能**：返回知识库里打了 `has_proactive_insight=True` 标记的段落索引
**代码**：
```python
@router.get("/annotated_paragraphs/{session_id}")
def get_annotated_paragraphs(session_id: str):
    from kb_client import get_client
    chroma = get_client()
    col = chroma.get_or_create_collection("woolf_works")
    results = col.get(
        where={"has_proactive_insight": True},
        include=["metadatas"]
    )
    para_ids = [m.get("para_idx") for m in results["metadatas"] if m.get("para_idx") is not None]
    return {"para_ids": para_ids}
```

#### 3. `mark_proactive_passages()` 函数
**位置**：`scripts/build_graph.py`（构建图之后调用）
**功能**：度数超过阈值的节点打标记写回 ChromaDB
**逻辑**：图里连接数多 = 跨 collection 关联丰富 = 值得主动解读
**代码**：
```python
def mark_proactive_passages(G: nx.Graph, degree_threshold: int = 3):
    chroma = get_client()
    for node_id, degree in G.degree():
        if degree < degree_threshold:
            continue
        node_data = dict(G.nodes[node_id])
        cname = node_data.get("collection")
        if not cname:
            continue
        try:
            col = chroma.get_collection(cname)
            node_data["has_proactive_insight"] = True
            col.update(ids=[node_id], metadatas=[node_data])
        except Exception:
            pass
```

### 前端（2项）

#### 4. AgentUI 摇杆导航
**位置**：`frontend/src/components/ReaderScreen.jsx` 的 `handleAgentNavEvent`
**功能**：Agent UI 打开时，摇杆上下键切换问题选项，action 键确认
**问题**：目前 `handleAgentNavEvent` 是空函数，AgentUI 只有键盘降级方案

#### 5. `confirm` case 清理
**位置**：`ReaderScreen.jsx` 的 `handleReadingEvent`
**问题**：重构后 `action` 事件合并了"进入选中"和"确认"逻辑，原来的 `confirm` case 是死代码，需删除

### 固件（1项）

#### 6. menuconfig 确认 WakeNet 模型
**操作**：
```bash
cd firmware
idf.py menuconfig
# 路径：Component config → ESP Speech Recognition → Wake word engine → WN9_HILEXIN
```
**原因**：`sdkconfig.defaults` 写了配置，但第一次编译前需要手动进 menuconfig 确认，否则编译时找不到模型文件

---

## 七、可复用的经验（跨项目适用）

### 经验 1：高 PPI 小屏的 CSS 缩放方案
当目标屏幕 PPI 极高（>400）时，桌面 Web App 的正确缩放方式：
- 确定"设计尺寸"（逻辑像素）= 物理像素 / 缩放倍数
- 在 `#root` 上用 `transform: scale(N) + transform-origin: top left`
- 所有 CSS 按逻辑像素写，实际输出自动放大 N 倍
- **不用** viewport meta（只对移动端生效）

### 经验 2：Web Serial API 的正确读取模式
串口数据以字节流形式到达，不保证按行对齐：
- 必须维护 `buffer` 字符串
- 按 `\n` 切割，`lines.pop()` 保留不完整的最后一行
- 固件侧必须 `fflush(stdout)` 否则数据卡在缓冲区

### 经验 3：固件事件设计原则
固件应该是**无状态的事件发射器**：
- 只发原始信号（action / cancel），不在固件里判断"当前是选中模式还是阅读模式"
- 状态由前端维护，前端根据当前状态解释同一个事件的含义
- 好处：固件简单稳定，交互逻辑改动只改前端

### 经验 4：I2S 麦克风数据格式
INMP441 等常见 MEMS 麦克风输出**左对齐 32-bit**：
- I2S 配置为 32-bit 位宽读取
- 有效 16-bit 音频数据在高位：`pcm = (int16_t)(raw >> 16)`
- 直接取低 16-bit 会得到全零或噪声

### 经验 5：WakeNet 防抖
检测到唤醒词后必须静默一段时间（1-1.5s）：
- 原因：WakeNet 每 32ms 推理一次，一次说话可能触发多次检测
- 不加防抖：一次唤醒 → 连续发 40+ 个 wake 事件 → 前端重复触发

---

## 八、调试工具速查

| 问题 | 工具 | 命令 |
|------|------|------|
| 查看固件串口输出 | ESP-IDF 串口监视器 | `idf.py monitor` |
| 浏览器调试 Web Serial | Chrome DevTools Console | `navigator.serial.getPorts()` |
| 查看 ChromaDB 内容 | Python 脚本 | `col.get(include=["metadatas"])` |
| 测试 API 端点 | curl | `curl -X POST localhost:8000/reader/suggest -d '{...}'` |
| 查看 NetworkX 图结构 | Python 脚本 | `print(nx.info(G))` |
