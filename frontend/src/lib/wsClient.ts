import type { ClientPayload, ServerMessage } from '../types/game'

type MessageHandler = (msg: ServerMessage) => void

export class WsClient {
  private ws: WebSocket | null = null
  private readonly url: string
  private readonly onMessage: MessageHandler
  private readonly reconnectDelay = 1500
  private destroyed = false

  constructor(url: string, onMessage: MessageHandler) {
    this.url = url
    this.onMessage = onMessage
  }

  connect(): void {
    if (this.destroyed) return
    this.ws = new WebSocket(this.url)

    this.ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as ServerMessage
        this.onMessage(msg)
      } catch {
        // ignore malformed frames
      }
    }

    this.ws.onclose = () => {
      if (!this.destroyed) {
        setTimeout(() => this.connect(), this.reconnectDelay)
      }
    }
  }

  send(payload: ClientPayload): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload))
    }
  }

  destroy(): void {
    this.destroyed = true
    this.ws?.close()
  }
}
