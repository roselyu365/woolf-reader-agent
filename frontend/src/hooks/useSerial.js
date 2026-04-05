import { useState, useCallback, useRef } from 'react'

export function useSerial(onEvent) {
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const portRef = useRef(null)

  const connect = useCallback(async () => {
    setError(null)
    try {
      // 弹出系统串口选择对话框，用户选择 ESP32-S3
      const port = await navigator.serial.requestPort()
      await port.open({ baudRate: 115200 })
      portRef.current = port
      setConnected(true)

      // 持续读取串口数据
      const reader = port.readable.getReader()
      let buffer = ''

      const readLoop = async () => {
        try {
          while (true) {
            const { value, done } = await reader.read()
            if (done) break

            buffer += new TextDecoder().decode(value)
            const lines = buffer.split('\n')
            buffer = lines.pop() // 保留不完整的行

            for (const line of lines) {
              const trimmed = line.trim()
              if (!trimmed) continue
              try {
                const event = JSON.parse(trimmed)
                onEvent(event)
              } catch {
                // 非 JSON 行忽略（调试输出等）
              }
            }
          }
        } catch {
          setConnected(false)
          setError('设备连接断开')
        } finally {
          reader.releaseLock()
        }
      }

      readLoop()
    } catch (err) {
      // 用户取消选择 or 连接失败
      if (err.name !== 'NotFoundError') {
        setError('连接失败，请检查设备是否插入')
      }
    }
  }, [onEvent])

  return { connected, error, connect }
}
