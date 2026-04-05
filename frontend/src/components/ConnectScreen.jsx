import React from 'react'

export default function ConnectScreen({ onConnect, onDemo, error }) {
  return (
    <div style={styles.container}>

      <div style={styles.title}>
        <span style={styles.titleMain}>WOOLF</span>
        <span style={styles.titleSub}>A Reading Companion</span>
      </div>

      <div style={styles.quote}>
        "A woman must have money and a room of her own."
      </div>

      <button style={styles.btn} onClick={onConnect}>
        连接阅读器
      </button>

      <button style={styles.demoBtn} onClick={onDemo}>
        演示模式（键盘）
      </button>

      {error && (
        <div style={styles.error}>{error}</div>
      )}

      <div style={styles.hint}>
        演示模式：↑↓ 移动光标 · Space 选段 · Enter 确认 · Esc 关闭
      </div>

    </div>
  )
}

const styles = {
  container: {
    width: '100%',
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '14px',
    background: '#0a0a0a',
  },
  title: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '3px',
  },
  titleMain: {
    fontSize: '22px',
    fontFamily: 'Georgia, serif',
    letterSpacing: '8px',
    color: '#e8e0d0',
  },
  titleSub: {
    fontSize: '8px',
    letterSpacing: '4px',
    color: '#6b6055',
    fontFamily: 'Georgia, serif',
  },
  quote: {
    fontSize: '9px',
    color: '#5a5248',
    fontStyle: 'italic',
    maxWidth: '320px',
    textAlign: 'center',
    lineHeight: '1.5',
  },
  btn: {
    padding: '7px 24px',
    background: 'transparent',
    border: '1px solid #6b6055',
    color: '#c8b89a',
    fontSize: '10px',
    letterSpacing: '2px',
    cursor: 'pointer',
    fontFamily: 'Georgia, serif',
    transition: 'all 0.2s',
  },
  error: {
    fontSize: '8px',
    color: '#a05050',
  },
  demoBtn: {
    padding: '5px 20px',
    background: 'transparent',
    border: '1px solid #3a3530',
    color: '#5a5248',
    fontSize: '8px',
    letterSpacing: '2px',
    cursor: 'pointer',
    fontFamily: 'Georgia, serif',
  },
  hint: {
    fontSize: '7px',
    color: '#3a3530',
    letterSpacing: '1px',
    textAlign: 'center',
    maxWidth: '320px',
  },
}
