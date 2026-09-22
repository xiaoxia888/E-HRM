import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { TaskListResponse } from '../types'

export function useTaskStream(): void {
  const queryClient = useQueryClient()

  useEffect(() => {
    let socket: WebSocket | null = null
    let reconnectTimer: number | null = null
    let stopped = false

    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(
        `${protocol}//${window.location.host}/api/v1/tasks/ws`,
      )
      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data) as TaskListResponse
        queryClient.setQueryData(['tasks'], payload)
      }
      socket.onclose = () => {
        if (!stopped) {
          reconnectTimer = window.setTimeout(connect, 2000)
        }
      }
    }

    connect()
    return () => {
      stopped = true
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [queryClient])
}
