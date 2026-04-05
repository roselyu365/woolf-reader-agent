import React, { useState, useRef, useCallback } from 'react'
import { useSerial } from './hooks/useSerial'
import ConnectScreen from './components/ConnectScreen'
import ReaderScreen from './components/ReaderScreen'

export default function App() {
  const [mode, setMode] = useState('connect')
  const [book, setBook] = useState('daluo_weifuren')
  const [demoMode, setDemoMode] = useState(false)

  // 轮询手机端约定的书目，检测到变化时自动切换
  React.useEffect(() => {
    const poll = () => {
      fetch('/mobile/scheduled_book')
        .then(r => r.json())
        .then(d => { if (d.book) setBook(prev => prev !== d.book ? d.book : prev) })
        .catch(() => {})
    }
    poll()
    const timer = setInterval(poll, 5000)
    return () => clearInterval(timer)
  }, [])

  // 事件订阅：ReaderScreen 注册回调，Serial hook 触发
  const listenerRef = useRef(null)

  const handleEvent = useCallback((event) => {
    listenerRef.current?.(event)
  }, [])

  const onSerialEvent = useCallback((fn) => {
    listenerRef.current = fn
    return () => { listenerRef.current = null }
  }, [])

  const { connected, error, connect } = useSerial(handleEvent)

  React.useEffect(() => {
    if (connected) setMode('reading')
  }, [connected])

  // 演示模式：键盘 → 模拟摇杆事件
  React.useEffect(() => {
    if (!demoMode) return
    const handler = (e) => {
      if (e.key === 'ArrowUp')    listenerRef.current?.({ event: 'cursor', value: 'up' })
      if (e.key === 'ArrowDown')  listenerRef.current?.({ event: 'cursor', value: 'down' })
      if (e.key === ' ')          { e.preventDefault(); listenerRef.current?.({ event: 'action' }) }
      if (e.key === 'Enter')      listenerRef.current?.({ event: 'action' })
      if (e.key === 'Escape')     listenerRef.current?.({ event: 'cancel' })
      if (e.key === 'w')          listenerRef.current?.({ event: 'wake' })
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [demoMode])

  const handleDemo = () => {
    setDemoMode(true)
    setMode('reading')
  }

  if (mode === 'connect') {
    return <ConnectScreen onConnect={connect} onDemo={handleDemo} error={error} />
  }

  return <ReaderScreen onSerialEvent={onSerialEvent} book={book} />
}
