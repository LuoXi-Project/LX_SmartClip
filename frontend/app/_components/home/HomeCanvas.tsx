'use client'

import { useEffect, useRef } from 'react'

type Particle = {
  x: number
  y: number
  vx: number
  vy: number
  size: number
}

export function HomeCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const mouseRef = useRef({ x: -9999, y: -9999 })
  const rafRef = useRef<number>()

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let particles: Particle[] = []
    const PARTICLE_COUNT = reducedMotion ? 0 : 72
    const CONNECT_DIST = 150
    const MOUSE_RADIUS = 200

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const rect = canvas.getBoundingClientRect()
      canvas.width = Math.floor(rect.width * dpr)
      canvas.height = Math.floor(rect.height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    const initParticles = () => {
      const w = canvas.getBoundingClientRect().width
      const h = canvas.getBoundingClientRect().height
      particles = Array.from({ length: PARTICLE_COUNT }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.35,
        vy: (Math.random() - 0.5) * 0.35,
        size: Math.random() * 1.4 + 0.4,
      }))
    }

    const drawGrid = (w: number, h: number) => {
      const gridSize = 56
      ctx.strokeStyle = 'rgba(34, 211, 238, 0.04)'
      ctx.lineWidth = 0.5
      for (let x = 0; x < w; x += gridSize) {
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, h)
        ctx.stroke()
      }
      for (let y = 0; y < h; y += gridSize) {
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(w, y)
        ctx.stroke()
      }
    }

    const onMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect()
      mouseRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top }
    }

    const onMouseLeave = () => {
      mouseRef.current = { x: -9999, y: -9999 }
    }

    const animate = () => {
      const w = canvas.getBoundingClientRect().width
      const h = canvas.getBoundingClientRect().height
      ctx.clearRect(0, 0, w, h)
      drawGrid(w, h)

      if (reducedMotion) {
        rafRef.current = requestAnimationFrame(animate)
        return
      }

      const mx = mouseRef.current.x
      const my = mouseRef.current.y

      for (const p of particles) {
        const dx = mx - p.x
        const dy = my - p.y
        const dist = Math.hypot(dx, dy)
        if (dist < MOUSE_RADIUS && dist > 1) {
          const force = ((MOUSE_RADIUS - dist) / MOUSE_RADIUS) * 0.035
          p.vx -= (dx / dist) * force
          p.vy -= (dy / dist) * force
        }

        p.x += p.vx
        p.y += p.vy

        if (p.x <= 0 || p.x >= w) {
          p.vx *= -1
          p.x = Math.max(0, Math.min(w, p.x))
        }
        if (p.y <= 0 || p.y >= h) {
          p.vy *= -1
          p.y = Math.max(0, Math.min(h, p.y))
        }

        p.vx *= 0.998
        p.vy *= 0.998

        ctx.beginPath()
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(34, 211, 238, 0.55)'
        ctx.fill()
      }

      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const a = particles[i]
          const b = particles[j]
          const dist = Math.hypot(a.x - b.x, a.y - b.y)
          if (dist < CONNECT_DIST) {
            const alpha = (1 - dist / CONNECT_DIST) * 0.4
            ctx.beginPath()
            ctx.moveTo(a.x, a.y)
            ctx.lineTo(b.x, b.y)
            ctx.strokeStyle = `rgba(129, 140, 248, ${alpha})`
            ctx.lineWidth = 0.6
            ctx.stroke()
          }
        }
      }

      if (mx > -5000) {
        const grad = ctx.createRadialGradient(mx, my, 0, mx, my, MOUSE_RADIUS * 1.2)
        grad.addColorStop(0, 'rgba(34, 211, 238, 0.12)')
        grad.addColorStop(0.5, 'rgba(99, 102, 241, 0.04)')
        grad.addColorStop(1, 'transparent')
        ctx.fillStyle = grad
        ctx.fillRect(0, 0, w, h)
      }

      rafRef.current = requestAnimationFrame(animate)
    }

    const onResize = () => {
      resize()
      initParticles()
    }

    resize()
    initParticles()
    window.addEventListener('resize', onResize)
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseleave', onMouseLeave)
    rafRef.current = requestAnimationFrame(animate)

    return () => {
      window.removeEventListener('resize', onResize)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseleave', onMouseLeave)
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 h-full w-full pointer-events-none"
      aria-hidden
    />
  )
}
