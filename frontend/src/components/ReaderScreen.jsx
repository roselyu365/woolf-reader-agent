import React, { useState, useEffect, useRef, useCallback } from 'react'
import AgentUI from './AgentUI'

const SESSION_ID = 'reader-' + Math.random().toString(36).slice(2, 8)

// 右侧状态条宽度
const STRIP_W = 52

export default function ReaderScreen({ onSerialEvent, book = 'a_room_of_ones_own' }) {
  const [paragraphs, setParagraphs] = useState([])
  const [cursorLine, setCursorLine] = useState(0)
  const [selStart, setSelStart] = useState(null)
  const [selEnd, setSelEnd] = useState(null)
  const [selecting, setSelecting] = useState(false)
  const [annotatedParas, setAnnotatedParas] = useState(new Set())
  const [proactiveBubble, setProactiveBubble] = useState(null) // { paraIdx, text }
  const [agentUI, setAgentUI] = useState(null) // { passage, questions }
  const [agentLoading, setAgentLoading] = useState(false)
  const scrollRef = useRef(null)
  const paraRefs = useRef([])
  // ref 版本：供事件回调读取最新值，避免 stale closure
  const paragraphsRef = useRef([])
  const selectingRef = useRef(false)
  const selStartRef = useRef(null)
  const selEndRef = useRef(null)
  const cursorLineRef = useRef(0)

  // ── 加载文本 ────────────────────────────────────────
  useEffect(() => {
    fetch(`/reader/text?book=${book}`)
      .then(r => r.json())
      .then(d => {
        setParagraphs(d.paragraphs)
        paragraphsRef.current = d.paragraphs
      })
      .catch(() => {
        // 后端未就绪时用占位文本
        setParagraphs(SAMPLE_PARAGRAPHS)
        paragraphsRef.current = SAMPLE_PARAGRAPHS
      })
  }, [book])

  // ── 加载有标注的段落 ─────────────────────────────────
  useEffect(() => {
    fetch(`/reader/annotated_paragraphs/${SESSION_ID}`)
      .then(r => r.json())
      .then(d => setAnnotatedParas(new Set(d.para_ids)))
      .catch(() => {})
  }, [])

  // ── 光标跟随滚动 ─────────────────────────────────────
  useEffect(() => {
    paraRefs.current[cursorLine]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [cursorLine])

  // ── 主动气泡轮询 ─────────────────────────────────────
  useEffect(() => {
    if (!annotatedParas.has(cursorLine)) return
    fetch(`/reader/proactive/${SESSION_ID}/${cursorLine}`)
      .then(r => r.json())
      .then(d => {
        if (d.text) setProactiveBubble({ paraIdx: cursorLine, text: d.text })
      })
      .catch(() => {})
  }, [cursorLine, annotatedParas])

  // ── 串口事件处理 ─────────────────────────────────────
  // 所有在回调里读取的状态都镜像到 ref，避免 stale closure
  const agentUIRef = useRef(null)
  useEffect(() => { agentUIRef.current = agentUI }, [agentUI])
  useEffect(() => { selectingRef.current = selecting }, [selecting])
  useEffect(() => { selStartRef.current = selStart }, [selStart])
  useEffect(() => { selEndRef.current = selEnd }, [selEnd])
  useEffect(() => { cursorLineRef.current = cursorLine }, [cursorLine])

  useEffect(() => {
    if (!onSerialEvent) return
    const unsub = onSerialEvent((event) => {
      if (agentUIRef.current) {
        handleAgentNavEvent(event, agentUIRef.current.questions.length)
      } else {
        handleReadingEvent(event)
      }
    })
    return unsub
  // 只在 onSerialEvent 变化时重新注册，内部用 ref 读最新状态
  }, [onSerialEvent])

  function handleReadingEvent(event) {
    switch (event.event) {
      case 'cursor':
        if (selectingRef.current) {
          setSelEnd(prev => Math.min((prev ?? 0) + 1, paragraphsRef.current.length - 1))
        } else {
          if (event.value === 'up')
            setCursorLine(l => Math.max(0, l - 1))
          if (event.value === 'down')
            setCursorLine(l => Math.min(paragraphsRef.current.length - 1, l + 1))
        }
        break

      case 'action':
        if (!selectingRef.current) {
          setSelecting(true)
          setSelStart(cursorLineRef.current)
          setSelEnd(cursorLineRef.current)
        } else {
          const s = selStartRef.current
          const e = selEndRef.current ?? s
          const passage = paragraphsRef.current.slice(s, e + 1).join(' ')
          triggerAgentUI(passage)
          setSelecting(false)
          setSelStart(null)
          setSelEnd(null)
        }
        break

      case 'wake':
        triggerAgentUI(paragraphsRef.current[cursorLineRef.current] ?? '')
        break

      case 'cancel':
        setSelecting(false)
        setSelStart(null)
        setSelEnd(null)
        break
    }
  }

  // agentSelectedIdx 用 ref 而非 state，避免 useEffect 依赖变化引起重新注册
  const agentSelectedIdxRef = useRef(0)

  function handleAgentNavEvent(event, questionCount) {
    switch (event.event) {
      case 'cursor':
        if (event.value === 'up') {
          agentSelectedIdxRef.current = Math.max(0, agentSelectedIdxRef.current - 1)
        }
        if (event.value === 'down') {
          // questionCount 个问题 + 1 个"加入笔记"选项
          agentSelectedIdxRef.current = Math.min(questionCount, agentSelectedIdxRef.current + 1)
        }
        // 通知 AgentUI 更新高亮
        setAgentUI(prev => prev ? { ...prev, _tick: Date.now() } : prev)
        break

      case 'action':
        // 确认当前选项
        setAgentUI(prev => prev ? { ...prev, _confirm: agentSelectedIdxRef.current } : prev)
        break

      case 'cancel':
        agentSelectedIdxRef.current = 0
        setAgentUI(null)
        break
    }
  }

  async function triggerAgentUI(passage) {
    setProactiveBubble(null)
    setAgentLoading(true)
    try {
      const res = await fetch('/reader/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: SESSION_ID, passage }),
      })
      const data = await res.json()
      setAgentUI({ passage, questions: data.questions })
    } catch {
      // 后端不通时展示空问题列表
      setAgentUI({ passage, questions: [] })
    } finally {
      setAgentLoading(false)
    }
  }

  const closeAgentUI = useCallback(() => setAgentUI(null), [])

  // ── 渲染 ─────────────────────────────────────────────
  const textW = 600 - STRIP_W

  return (
    <div style={{ width: 600, height: 270, display: 'flex', position: 'relative', background: '#0a0a0a' }}>

      {/* ── 左侧文本区 ── */}
      <div ref={scrollRef} style={{ width: textW, height: 270, overflowY: 'hidden', padding: '18px 16px 18px 20px' }}>
        {paragraphs.map((para, i) => {
          const isCursor  = i === cursorLine && !selecting
          const isSelected = selecting && selStart != null &&
            i >= Math.min(selStart, selEnd ?? selStart) &&
            i <= Math.max(selStart, selEnd ?? selStart)

          return (
            <p
              key={i}
              ref={el => paraRefs.current[i] = el}
              style={{
                fontSize: '11px',
                lineHeight: '1.7',
                color: isCursor ? '#e8e0d0' : isSelected ? '#f0e8d8' : '#7a7068',
                background: isSelected
                  ? 'rgba(160,130,90,0.18)'
                  : isCursor
                    ? 'rgba(255,255,255,0.03)'
                    : 'transparent',
                borderLeft: isCursor ? '2px solid #8a7a65' : '2px solid transparent',
                paddingLeft: '8px',
                marginBottom: '10px',
                transition: 'color 0.15s, background 0.15s',
                cursor: 'default',
              }}
            >
              {para}
            </p>
          )
        })}
      </div>

      {/* ── 右侧状态条（压缩到 52px）── */}
      <div style={{
        width: STRIP_W,
        height: 270,
        borderLeft: '1px solid #1e1c18',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '14px 0',
        flexShrink: 0,
      }}>
        {/* 段落计数 */}
        <div style={{ fontSize: '8px', color: '#3a3530', letterSpacing: '1px', textAlign: 'center' }}>
          <div style={{ color: '#6b6055' }}>{cursorLine + 1}</div>
          <div style={{ color: '#2a2520', marginTop: 2 }}>/{paragraphs.length}</div>
        </div>

        {/* 进度条 */}
        <div style={{ width: 1, flex: 1, background: '#1a1815', margin: '8px 0', position: 'relative' }}>
          <div style={{
            position: 'absolute',
            top: `${paragraphs.length ? (cursorLine / paragraphs.length) * 100 : 0}%`,
            left: -3, width: 7, height: 7,
            borderRadius: '50%',
            background: '#6b6055',
          }} />
        </div>

        {/* 标注指示点 */}
        <div style={{
          width: 6, height: 6,
          borderRadius: '50%',
          background: annotatedParas.has(cursorLine) ? '#a07850' : '#1e1c18',
          transition: 'background 0.3s',
        }} title={annotatedParas.has(cursorLine) ? '有 Woolf 解读' : ''} />
      </div>

      {/* ── 主动气泡（浮层）── */}
      {proactiveBubble && !agentUI && (
        <div style={{
          position: 'absolute',
          bottom: 12, left: 20,
          width: textW - 32,
          background: '#161310',
          border: '1px solid #3a3020',
          padding: '7px 10px',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <div style={{ width: 4, height: 4, borderRadius: '50%', background: '#a07850', flexShrink: 0 }} />
          <div style={{ fontSize: '9px', color: '#8a7a65', fontStyle: 'italic', lineHeight: 1.5, flex: 1 }}>
            {proactiveBubble.text}
          </div>
          <button
            onClick={() => setProactiveBubble(null)}
            style={{ background: 'none', border: 'none', color: '#3a3530', fontSize: 10, cursor: 'pointer' }}
          >✕</button>
        </div>
      )}

      {/* ── 加载中提示 ── */}
      {agentLoading && (
        <div style={{
          position: 'absolute', inset: 0,
          background: 'rgba(10,10,10,0.85)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{ fontSize: '9px', color: '#6b6055', letterSpacing: '3px' }}>— thinking —</div>
        </div>
      )}

      {/* ── Agent UI 全屏叠加 ── */}
      {agentUI && (
        <AgentUI
          passage={agentUI.passage}
          questions={agentUI.questions}
          sessionId={SESSION_ID}
          onClose={closeAgentUI}
          selectedIdxRef={agentSelectedIdxRef}
          confirmSignal={agentUI._confirm}
          tick={agentUI._tick}
        />
      )}
    </div>
  )
}

// 后端未就绪时的占位文本
const SAMPLE_PARAGRAPHS = [
  "But, you may say, we asked you to speak about women and fiction—what has that got to do with a room of one's own?",
  "I will try to explain. When you asked me to speak about women and fiction I sat down on the banks of a river and began to wonder what the words meant.",
  "They might mean simply a few remarks about Fanny Burney; a few more about Jane Austen; a tribute to the Brontës and a sketch of Haworth Parsonage under snow.",
  "Or they might mean women and what they are like; or they might mean women and the fiction that they write; or they might mean women and the fiction that is written about them.",
  "It was thus that I found myself walking with extreme rapidity across a grass plot. Instantly a man's figure rose to intercept me.",
  "His face expressed horror and indignation. Instinct rather than reason came to my help; he was a Beadle; I was a woman. This was the turf; there was the path.",
  "Only the Fellows and Scholars are allowed here; the gravel is the place for me.",
  "Such thoughts were the work of a moment. As I regained the path the arms of the Beadle sank, his face assumed its usual repose.",
]
