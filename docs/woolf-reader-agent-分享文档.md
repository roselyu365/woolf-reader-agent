# 用 AI 复活弗吉尼亚·伍尔夫——Reader Agent 制作全记录

> 一个"陪你读书的作家"的设计与实现过程

---

## 这是什么

一个运行在两个端点的 Virginia Woolf AI 伴读助手：

- **手机端**：像一个存在于通讯录里的"联系人"，可以随时和伍尔夫对话
- **阅读器端**：在你读《一间自己的房间》时，伍尔夫在旁边，你可以划词提问、聊主题、聊感受

技术上：单个 FastAPI 后端，ChromaDB 本地知识库，Claude API，WebSocket 流式输出。

---

## 一、从想法到设计：问了哪些问题

这个项目的设计过程是一次连续的"澄清对话"。每个问题都在缩小设计空间。

### 最关键的几个决策点

| 问题 | 选项 | 最终决策 | 为什么 |
|------|------|----------|--------|
| 做几个作家？ | 多个 vs 只做伍尔夫 | 只做伍尔夫 | 人格一致性比覆盖广度更重要 |
| 作品范围？ | 多本 vs 一本 | 主做《一间自己的房间》 | 先跑通一本，深度优先 |
| 当代人物用谁？ | 泛化 vs 具体人物 | Vita + Katherine Mansfield | 有真实书信/日记，可引用真实材料 |
| 知识库放哪？ | 云端 vs 本地 | 本地 ChromaDB | 黑客松场景，延迟低，无服务依赖 |
| 交互模式做几个？ | 1 种 vs 全做 | 全部 4 种 | 黑客松展示价值，做完整 |

### 一个关键的设计争论

**探究对话要不要 fallback？**

初版设计：如果用户没有偏好，跳过 5 轮探究，直接推荐。

被否定了——理由是：**探究本身就是体验**，不是获取偏好的手段。就像书的第一页不能因为你"不知道自己想看什么"就被跳过。

最终版：5 轮固定探究，永远执行，无任何 fallback。

---

## 二、架构设计

整体用 **CoALA 框架**（认知架构，分 Memory / Decision / Action 三层）思考。

```
手机端 App          阅读器设备
     │                  │
     ▼                  ▼
  FastAPI 后端 (/mobile/ws, /reader/ws)
          │
     DECISION LAYER
     场景路由 → 4 种推理范式
          │
     ACTION LAYER
     统一 retrieve() 工具
          │
     MEMORY LAYER
     7 个 ChromaDB collection
```

### 知识库：7 个 Collection

```
woolf_works         《一间自己的房间》正文
woolf_biography     日记（1928-29）+ 书信
woolf_contemporaries  Vita + Mansfield 相关资料
woolf_historical    布鲁姆斯伯里、女性参政、一战背景
woolf_annotations   学术注释
user_notes          用户高亮和笔记
conversation_memory 对话摘要（每 5 轮自动生成）
```

所有 collection 使用 cosine 距离（这个细节后来出了 bug，见第三节）。

### 检索管道：4 步

```
Step-back 查询扩展（表面问题 → 2-3 个深层查询）
  ↓
向量检索（多 collection 并行）
  ↓
GraphRAG 主题扩展（9 个固定主题标签构建图，NetworkX）
  ↓
MMR 重排序（相关性 + 多样性，λ=0.6）
```

**为什么加 GraphRAG？**

纯向量检索会漏掉"深层逻辑上相关但语义距离较远"的内容。比如问"伍尔夫对独立的看法"，向量检索能找到直接论述独立的段落，但可能漏掉她在日记里写的、关于"没有自己的房间"的愤怒——这两者在主题图上是连通的。

9 个主题标签是**固定**的（不让模型自由标注），保证图的一致性和连通性。

### Decision 层：4 个场景 × 4 种推理范式

| 场景 | 触发条件 | 推理范式 |
|------|----------|----------|
| 首次探究对话 | 新 session | Dialogue State Machine（5 轮固定） |
| 深度阅读问答 | 默认 | ReAct（Reason + Act 工具调用循环） |
| 主题探索 | 含"throughout"/"theme of"等信号词 | Plan-and-Execute（分解子问题 + 并行检索） |
| 段落注释 | 用户高亮了文本 | RAG Pipeline（单次检索直接注释） |

不同场景需要不同的推理深度，统一用 ReAct 既浪费又不够准确。

### Persona 系统

伍尔夫的人格锚定来自 `persona_anchors.json`：
- **6 个声音锚点**：她真实说话的方式特征
- **6 个禁止短语**：AI 常见的迎合句，全部禁止
- **9 个伍尔夫真实引文池**：用于探究问题的开场白
- **5 个探究问题**：每个都以真实引文开场，不用抽象比喻

**防漂移机制**：每 5 轮自动摘要对话，存入 `conversation_memory`，下轮注入压缩上下文，防止长对话中人格偏移。

---

## 三、实现过程：踩了哪些坑

按照"实现 → spec review → code quality review"循环做了 10 个 task。26 个测试全部通过。以下是真正有代表性的问题。

### 坑 1：ChromaDB cosine metric 没配置

**现象**：知识库查询出来的"相似度"数值不对，有时候返回大于 1 的值。

**原因**：ChromaDB 默认用 L2 距离，但相似度计算公式是 `1 - distance`，只有 cosine 才有意义。创建 collection 时没有传 `metadata={"hnsw:space": "cosine"}`。

**修复**：
```python
# 错误
chroma.get_or_create_collection("woolf_works")

# 正确
chroma.get_or_create_collection(
    "woolf_works",
    metadata={"hnsw:space": "cosine"},
    embedding_function=embedding_fn
)
```

**注意**：已有的 collection 改不了 metric，必须重建。

---

### 坑 2：GraphRAG 节点 ID 对不上（Critical）

**现象**：GraphRAG 扩展逻辑跑了，但实际上什么都没扩展到——图节点完全没被命中。

**原因**：向量检索返回的 metadata 里有 `chunk_idx`（整数，如 42），但图节点 ID 是 ChromaDB 的文档 ID（字符串，如 `works_42`）。两者格式不一致，`G.has_node("42")` 永远 False。

**修复**：
```python
# 错误：用 metadata 里的 chunk_idx
node_id = str(meta.get("chunk_idx"))

# 正确：用 ChromaDB 返回的文档 ID
node_id = res["ids"][0]   # 这才是真实的图节点 ID
```

这个 bug 是"静默失败"——代码不报错，GraphRAG 逻辑完整跑完，只是什么都没发生。

---

### 坑 3：async 函数里调用同步的 Claude API

**现象**：WebSocket 连接偶发卡住，FastAPI 事件循环偶尔阻塞。

**原因**：`anthropic.Anthropic.messages.create()` 是同步阻塞调用，在 async 函数里直接调用会阻塞整个 event loop。

**修复**：用 `asyncio.to_thread()` 包装：
```python
# 错误
response = self.client.messages.create(...)

# 正确
response = await asyncio.to_thread(self.client.messages.create, **kwargs)
```

---

### 坑 4：PEP 479 —— async generator 里不能 raise StopIteration

**现象**：`RuntimeError: async generator raised StopIteration`

**原因**：Python 3.7+ 在 async generator 里 raise StopIteration 会被自动转换为 RuntimeError（PEP 479）。`dialogue_state.py` 用 StopIteration 来表示对话结束。

**修复**：自定义异常：
```python
class DialogueComplete(Exception):
    pass

# 用 DialogueComplete 替代 StopIteration
```

---

### 坑 5：线程竞争 —— proactive buffer 没加锁

**现象**：偶发 KeyError，多个请求同时访问 proactive buffer 时数据损坏。

**原因**：FastAPI 的 BackgroundTasks 在单独线程运行，主线程同时读写 `_proactive_buffer` 这个 dict，没有任何同步机制。

**修复**：加 `threading.Lock()`，所有读写操作在 `with _proactive_lock:` 里进行。

---

### 坑 6：api/main.py 找不到自己的模块

**现象**：启动服务器报 `ModuleNotFoundError: No module named 'notes_router'`

**原因**：从项目根目录运行时，Python 的 `sys.path` 不包含 `api/` 子目录。

**修复**：在 `main.py` 最开头加一行：
```python
sys.path.insert(0, str(Path(__file__).parent))
```

---

## 四、设计回顾：哪些判断是对的，哪些判断是错的

### 对的

1. **固定主题标签做 GraphRAG**：不让模型自由标注，保证了图的稳定性
2. **4 种场景分开推理**：ReAct 适合深度问答，DSM 适合探究，不该混用
3. **Persona 引用真实原文**：初版用了抽象比喻（"你的阅读状态像什么季节"），用户觉得太虚。改成引用伍尔夫真实文字后感觉对了
4. **探究不设 fallback**：这个设计原则后来成了整个项目最有价值的洞察之一

### 错的（或遗漏的）

1. **基础设施选型没在第一轮问**：知识库用本地还是云、同步还是异步，应该是设计的第一个问题，但被延后了
2. **工具调用预设了路由规则**：不该预定义"什么问题走什么工具"，应该让 agent 自行判断
3. **Step-back 和 GraphRAG 被当成了优化项**：其实应该是基线设计的一部分，因为它们解决的是核心问题（深层逻辑检索），不是锦上添花
4. **Decision 层设计太模糊**：最初写"LLM 调工具"，这不是推理范式，只是描述了一个动作

---

## 五、还没解决的问题

### 1. 流式输出是模拟的，不是真正的 SSE

**现在怎么做的**：把完整回复生成完，逐字符 yield 出来，模拟"正在打字"的效果。

**真正的问题**：用户要等完整回复生成完才开始看到内容。对于长回复（比如主题探索），延迟感明显。

**正确做法**：
```python
# 用 AsyncAnthropic + stream
async with client.messages.stream(...) as stream:
    async for text in stream.text_stream:
        yield text
```

改动不大，但需要把 `Anthropic` 换成 `AsyncAnthropic`，所有调用改成 async with stream。

---

### 2. 主动触发逻辑不看内容

**现在怎么做的**：用户每次发消息后，无条件预生成后续 3 个段落的"伍尔夫插话"，但 prompt 里只有段落编号，不知道那段实际写了什么。

**问题**：生成的插话和书的内容完全脱节。

**正确做法有两条路**：
- **标注触发点**：在 `bookText` 里手动标出 10-15 个值得触发的段落（关键主题句），只在这些位置预生成
- **内容感知**：把段落实际文本传给 prompt，让伍尔夫针对具体内容回应

两者不互斥，标注触发点保证时机准确，内容感知保证质量。

---

### 3. 移动端 → 阅读器偏好没有同步

**背景**：系统设计里，用户在手机端的 5 轮探究对话，应该能影响阅读器端的主动触发——知道你喜欢"意识流技法"分析，阅读器就更多触发相关段落。

**现在的状态**：两个端点完全独立，session 隔离，互相不知道对方的对话。

**解决方向**：用 `user_profile` 结构体存跨端偏好，移动端探究完成时写入，阅读器端启动时读取。

---

## 六、文件地图

```
workspace/reader-agent/
  agent/
    agent.py          主 agent（场景路由 + 4 种推理）
    scenarios.py      场景检测逻辑
    dialogue_state.py 探究对话状态机
    persona.py        伍尔夫人格系统
    tools.py          工具定义 + 执行器
  api/
    main.py           FastAPI 入口
    reader_router.py  阅读器端点（含主动触发）
    mobile_router.py  手机端点
    notes_router.py   用户笔记 CRUD
  scripts/
    kb_client.py      ChromaDB 封装
    retrieval.py      统一检索管道（Step-back + 向量 + GraphRAG + MMR）
    build_graph.py    构建主题图
    ingest_*.py       各 collection 入库脚本（5 个）
  data/
    persona_anchors.json  伍尔夫人格配置
    raw/              原始文本（现已下载完整）
  tests/              26 个测试，全部通过
  docs/
    woolf-reader-agent-分享文档.md   ← 本文件
```

---

## 结语

这个项目最有意思的地方不是技术，是**"如何设计一个有人格的 agent"**这个问题本身。

让 AI 说话像某个真实的人，不是 prompt 里加几句"你是伍尔夫"就够的。需要：真实引文作为锚点、禁止通用 AI 口癖、有防漂移机制、知识库里有她真实说过的话。

而且——**对话设计不是 UX 点缀，是核心产品逻辑**。"打开书的第一刻"是什么体验，决定了用户有没有被带入这个世界。这比技术架构更难设计，也更值得花时间。
