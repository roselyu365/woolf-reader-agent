import React, { useState, useEffect, useRef, useCallback } from 'react'

export default function AgentUI({
  passage, questions, sessionId, onClose,
  // 摇杆导航信号（来自 ReaderScreen 通过 agentUI state 传入）
  selectedIdxRef,   // React ref，读当前高亮 index
  confirmSignal,    // 变化时触发确认（值为选中 index）
  tick,             // 变化时强制重渲（摇杆移动时）
}) {
  const selected = selectedIdxRef?.current ?? 0
  const [response, setResponse] = useState(null)
  const [streaming, setStreaming] = useState(false)
  const [freeInput, setFreeInput] = useState('')
  const [showFreeInput, setShowFreeInput] = useState(false)
  const [noteSaved, setNoteSaved] = useState(false)
  const inputRef = useRef(null)

  // 自由提问输入框打开后自动聚焦
  useEffect(() => {
    if (showFreeInput) inputRef.current?.focus()
  }, [showFreeInput])

  // 键盘降级（没有摇杆时可用键盘调试）
  useEffect(() => {
    const onKey = (e) => {
      if (showFreeInput) return  // 输入框打开时不拦截
      if (!selectedIdxRef) return
      if (e.key === 'ArrowUp')   { selectedIdxRef.current = Math.max(0, selectedIdxRef.current - 1) }
      if (e.key === 'ArrowDown') { selectedIdxRef.current = Math.min(questions.length + 1, selectedIdxRef.current + 1) }
      if (e.key === 'Enter')     confirmChoice(selectedIdxRef.current)
      if (e.key === 'Escape')    onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [questions, showFreeInput])

  // 摇杆 action 信号 → 触发确认
  useEffect(() => {
    if (confirmSignal == null) return
    confirmChoice(confirmSignal)
  }, [confirmSignal])

  async function confirmChoice(idx) {
    if (idx === questions.length) {
      // "自主提问"
      setShowFreeInput(true)
      return
    }
    if (idx === questions.length + 1) {
      await addNote()
      onClose()
      return
    }
    const question = questions[idx]
    await askQuestion(question)
  }

  async function askQuestion(question) {
    setShowFreeInput(false)
    setResponse('')
    setStreaming(true)

    try {
      const res = await fetch('/reader/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message: question,
          highlighted_passage: passage,
        }),
      })

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop()
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6)
          if (payload === '[DONE]') { setStreaming(false); return }
          try {
            const { text } = JSON.parse(payload)
            setResponse(prev => (prev || '') + text)
          } catch {}
        }
      }
    } catch {
      setResponse('— connection lost —')
    } finally {
      setStreaming(false)
    }
  }

  async function addNote() {
    await fetch('/notes/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        content: passage,
        woolf_related: true,
      }),
    }).catch(() => {})
    setNoteSaved(true)
    setTimeout(() => onClose(), 1200)
  }

  const totalOptions = questions.length + 2  // questions + 自主提问 + 加入笔记

  return (
    <div style={styles.overlay}>

      {/* 选中段落 */}
      <div style={styles.passage}>
        "{passage.length > 120 ? passage.slice(0, 120) + '…' : passage}"
      </div>

      {/* 分割线 */}
      <div style={styles.divider} />

      {/* 如果还没选问题且不在输入状态：显示问题列表 */}
      {!response && !streaming && !showFreeInput && (
        <>
          {questions.map((q, i) => (
            <div
              key={i}
              onClick={() => askQuestion(q)}
              style={{
                ...styles.option,
                color: selected === i ? '#e8e0d0' : '#5a5248',
                background: selected === i ? 'rgba(160,130,90,0.1)' : 'transparent',
                borderLeft: selected === i ? '2px solid #8a7a65' : '2px solid transparent',
                cursor: 'pointer',
              }}
            >
              {q}
            </div>
          ))}

          {/* 自主提问 */}
          <div
            onClick={() => setShowFreeInput(true)}
            style={{
              ...styles.option,
              color: selected === questions.length ? '#c8b89a' : '#4a4540',
              borderLeft: selected === questions.length ? '2px solid #8a7a65' : '2px solid transparent',
              cursor: 'pointer',
              marginTop: 2,
            }}
          >
            ✎ 自己提问
          </div>

          {/* 加入笔记 */}
          <div
            onClick={async () => { await addNote(); onClose() }}
            style={{
              ...styles.option,
              color: selected === questions.length + 1 ? '#a07850' : '#3a3530',
              borderLeft: selected === questions.length + 1 ? '2px solid #a07850' : '2px solid transparent',
              cursor: 'pointer',
              marginTop: 2,
            }}
          >
            📝 加入笔记
          </div>
        </>
      )}

      {/* 自主提问输入框 */}
      {showFreeInput && !response && !streaming && (
        <div style={{ marginTop: 4 }}>
          <input
            ref={inputRef}
            value={freeInput}
            onChange={e => setFreeInput(e.target.value)}
            onKeyDown={e => {
              e.stopPropagation()  // 阻止 demo 模式键盘事件冒泡到 App.jsx
              if (e.key === 'Enter' && freeInput.trim()) askQuestion(freeInput.trim())
              if (e.key === 'Escape') setShowFreeInput(false)
            }}
            placeholder="输入你的问题…"
            style={styles.freeInput}
          />
          <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
            <button
              onClick={() => freeInput.trim() && askQuestion(freeInput.trim())}
              style={styles.sendBtn}
            >
              提问
            </button>
            <button
              onClick={() => setShowFreeInput(false)}
              style={{ ...styles.sendBtn, background: 'none', color: '#5a5248' }}
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* 正在响应 */}
      {streaming && (
        <div style={styles.responseText}>
          <span style={{ color: '#4a4540' }}>— thinking —</span>
        </div>
      )}

      {/* 显示 Agent 回复 */}
      {response && (
        <div style={styles.responseText}>
          {response}
          {streaming && <span style={{ opacity: 0.5 }}>▌</span>}
        </div>
      )}

      {/* 笔记已保存提示 */}
      {noteSaved && (
        <div style={{ fontSize: '10px', color: '#a07850', textAlign: 'center', marginTop: 8 }}>
          ✓ 已加入笔记
        </div>
      )}

      {/* 关闭按钮 */}
      <button onClick={onClose} style={styles.close}>✕</button>

    </div>
  )
}

const styles = {
  overlay: {
    position: 'absolute',
    inset: 0,
    background: '#0d0b09',
    padding: '14px 20px 12px',
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
    overflowY: 'auto',
  },
  passage: {
    fontSize: '9px',
    color: '#5a5248',
    fontStyle: 'italic',
    lineHeight: 1.5,
    maxHeight: 40,
    overflow: 'hidden',
  },
  divider: {
    height: 1,
    background: '#1e1c18',
    margin: '2px 0',
  },
  option: {
    fontSize: '10px',
    lineHeight: 1.5,
    padding: '3px 8px',
    transition: 'all 0.1s',
  },
  responseText: {
    fontSize: '10px',
    color: '#c8b89a',
    lineHeight: 1.7,
    fontStyle: 'italic',
    flex: 1,
    overflow: 'hidden',
  },
  freeInput: {
    width: '100%',
    background: '#1a1815',
    border: '1px solid #3a3530',
    borderRadius: 4,
    color: '#c8b89a',
    fontSize: '10px',
    padding: '4px 8px',
    outline: 'none',
    boxSizing: 'border-box',
  },
  sendBtn: {
    background: '#2a2520',
    border: '1px solid #3a3530',
    borderRadius: 4,
    color: '#8a7a65',
    fontSize: '9px',
    padding: '2px 10px',
    cursor: 'pointer',
  },
  close: {
    position: 'absolute',
    top: 10, right: 14,
    background: 'none',
    border: 'none',
    color: '#3a3530',
    fontSize: 10,
    cursor: 'pointer',
  },
}
