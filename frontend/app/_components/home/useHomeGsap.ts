'use client'

import { useEffect, type RefObject } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)

export function useHomeGsap(rootRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = rootRef.current
    if (!root) return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      gsap.set(root.querySelectorAll('[data-gsap]'), { clearProps: 'all', opacity: 1, y: 0, scale: 1 })
      return
    }

    const magneticCleanups: (() => void)[] = []

    const ctx = gsap.context(() => {
      const titleChars = root.querySelectorAll('[data-hero="title-char"]')
      const tl = gsap.timeline({ defaults: { ease: 'power4.out' } })

      tl.from('[data-hero="logo"]', {
        scale: 0.3,
        opacity: 0,
        rotation: -12,
        duration: 1.1,
        ease: 'back.out(1.6)',
      })
        .from(
          '[data-hero="tag"]',
          { y: 28, opacity: 0, letterSpacing: '0.6em', duration: 0.7 },
          '-=0.55',
        )
        .from(
          titleChars.length ? titleChars : '[data-hero="title"]',
          {
            y: 80,
            opacity: 0,
            rotateX: -40,
            stagger: titleChars.length ? 0.06 : 0,
            duration: 0.75,
            ease: 'power3.out',
          },
          '-=0.45',
        )
        .from('[data-hero="sub"]', { y: 32, opacity: 0, duration: 0.65 }, '-=0.35')
        .from('[data-hero="desc"]', { y: 20, opacity: 0, duration: 0.55 }, '-=0.4')
        .from(
          '[data-hero="cta"]',
          { y: 24, opacity: 0, scale: 0.92, stagger: 0.12, duration: 0.6 },
          '-=0.3',
        )
        .from('[data-hero="pipeline"]', { opacity: 0, scaleX: 0, duration: 0.8, ease: 'power2.inOut' }, '-=0.2')

      gsap.to('[data-hero="title-char"]', {
        backgroundPosition: '200% center',
        duration: 4,
        repeat: -1,
        ease: 'none',
        stagger: 0.15,
      })

      gsap.from('[data-section="status"]', {
        scrollTrigger: {
          trigger: '[data-section="status"]',
          start: 'top 85%',
          toggleActions: 'play none none reverse',
        },
        y: 50,
        opacity: 0,
        scale: 0.96,
        duration: 0.9,
        ease: 'power3.out',
      })

      gsap.from('[data-section="features-header"]', {
        scrollTrigger: {
          trigger: '[data-section="features"]',
          start: 'top 82%',
        },
        y: 40,
        opacity: 0,
        duration: 0.7,
      })

      gsap.from('[data-feature-card]', {
        scrollTrigger: {
          trigger: '[data-section="features"]',
          start: 'top 75%',
        },
        y: 70,
        opacity: 0,
        rotateY: -8,
        stagger: 0.1,
        duration: 0.85,
        ease: 'power3.out',
      })

      gsap.from('[data-section="cta-bottom"]', {
        scrollTrigger: {
          trigger: '[data-section="cta-bottom"]',
          start: 'top 88%',
        },
        y: 36,
        opacity: 0,
        duration: 0.75,
      })

      const magneticEls = root.querySelectorAll<HTMLElement>('[data-magnetic]')
      magneticEls.forEach((el) => {
        const strength = 0.35
        const onMove = (e: MouseEvent) => {
          const rect = el.getBoundingClientRect()
          const cx = rect.left + rect.width / 2
          const cy = rect.top + rect.height / 2
          const dx = (e.clientX - cx) / rect.width
          const dy = (e.clientY - cy) / rect.height
          gsap.to(el, {
            x: dx * 12 * strength,
            y: dy * 8 * strength,
            duration: 0.35,
            ease: 'power2.out',
          })
        }
        const onLeave = () => {
          gsap.to(el, { x: 0, y: 0, duration: 0.6, ease: 'elastic.out(1, 0.5)' })
        }
        el.addEventListener('mousemove', onMove)
        el.addEventListener('mouseleave', onLeave)
        magneticCleanups.push(() => {
          el.removeEventListener('mousemove', onMove)
          el.removeEventListener('mouseleave', onLeave)
        })
      })
    }, root)

    return () => {
      magneticCleanups.forEach((fn) => fn())
      ctx.revert()
    }
  }, [rootRef])
}
