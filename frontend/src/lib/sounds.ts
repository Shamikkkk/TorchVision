let ctx: AudioContext | null = null

function getCtx(): AudioContext {
  if (!ctx) ctx = new AudioContext()
  return ctx
}

function tone(
  frequency: number,
  duration: number,
  type: OscillatorType = 'sine',
  gain = 0.3,
  startTime?: number,
): void {
  const c = getCtx()
  const osc = c.createOscillator()
  const g = c.createGain()
  osc.connect(g)
  g.connect(c.destination)
  osc.type = type
  osc.frequency.value = frequency
  g.gain.setValueAtTime(gain, startTime ?? c.currentTime)
  g.gain.exponentialRampToValueAtTime(0.0001, (startTime ?? c.currentTime) + duration)
  osc.start(startTime ?? c.currentTime)
  osc.stop((startTime ?? c.currentTime) + duration)
}

export function playMove(): void {
  tone(880, 0.08, 'sine', 0.2)
}

export function playCapture(): void {
  tone(220, 0.12, 'triangle', 0.35)
}

export function playCheck(): void {
  tone(1200, 0.1, 'square', 0.25)
}

export function playGameEnd(): void {
  const c = getCtx()
  const now = c.currentTime
  tone(523.25, 0.25, 'sine', 0.3, now)
  tone(659.25, 0.25, 'sine', 0.3, now + 0.18)
  tone(783.99, 0.45, 'sine', 0.3, now + 0.36)
}
