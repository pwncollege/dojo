'use client'

import { useEffect, useRef, useCallback } from 'react'
import * as THREE from 'three'

export function AnimatedBackground() {
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<THREE.Scene | null>(null)
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const particlesRef = useRef<THREE.Mesh[]>([])
  const animationIdRef = useRef<number | null>(null)

  const init = useCallback(() => {
    if (!containerRef.current) {
      console.log('Container not ready, retrying...')
      setTimeout(init, 100)
      return
    }

    // Clean up any existing scene
    if (rendererRef.current) {
      console.log('Cleaning up old scene...')
      if (animationIdRef.current !== null) {
        cancelAnimationFrame(animationIdRef.current)
        animationIdRef.current = null
      }
      particlesRef.current.forEach(particle => {
        particle.geometry.dispose()
        const material = particle.material as THREE.MeshStandardMaterial
        material.map?.dispose()
        material.dispose()
      })
      rendererRef.current.dispose()
      if (rendererRef.current.domElement.parentNode === containerRef.current) {
        containerRef.current.removeChild(rendererRef.current.domElement)
      }
    }

    console.log('AnimatedBackground: Initializing...')

    // Scene setup
    const scene = new THREE.Scene()
    sceneRef.current = scene

    const camera = new THREE.PerspectiveCamera(
      75,
      window.innerWidth / window.innerHeight,
      0.1,
      1000
    )
    camera.position.z = 5
    cameraRef.current = camera

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })
    renderer.setSize(window.innerWidth, containerRef.current.offsetHeight)
    renderer.setClearColor(0x000000, 0)
    containerRef.current.appendChild(renderer.domElement)
    rendererRef.current = renderer

    // Get theme color - parse OKLCH or hex to THREE.Color
    const getColor = () => {
      const style = getComputedStyle(document.documentElement)
      const primary = style.getPropertyValue('--primary').trim()

      if (!primary) {
        return new THREE.Color(0x8b5cf6)
      }

      // Parse hex
      if (primary.startsWith('#')) {
        return new THREE.Color(primary)
      }

      // Parse OKLCH format: oklch(L C H)
      if (primary.startsWith('oklch')) {
        const match = primary.match(/oklch\(([\d.]+)\s+([\d.]+)\s+([\d.]+)\)/)
        if (match) {
          const [, l, c, h] = match.map(parseFloat)

          // Convert OKLCH to approximate RGB (simplified conversion)
          // For now, use CSS to render it and extract the computed color
          const testEl = document.createElement('div')
          testEl.style.color = primary
          document.body.appendChild(testEl)
          const computed = getComputedStyle(testEl).color
          document.body.removeChild(testEl)

          // Parse rgb(r, g, b)
          const rgbMatch = computed.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/)
          if (rgbMatch) {
            const [, r, g, b] = rgbMatch.map(Number)
            return new THREE.Color(r / 255, g / 255, b / 255)
          }
        }
      }

      return new THREE.Color(0x8b5cf6)
    }

    // Subtle fog for depth
    scene.fog = new THREE.FogExp2(0x000000, 0.012)

    // Strong ambient light - keep everything visible
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6)
    scene.add(ambientLight)

    // Main directional light - static
    const mainLight = new THREE.DirectionalLight(getColor(), 1.5)
    mainLight.position.set(0, 10, 10)
    scene.add(mainLight)

    // Create Matrix characters
    const chars = '01アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン'
    particlesRef.current = []
    const particleCount = 1000

    // Create canvas texture for characters
    const createCharTexture = (char: string) => {
      const canvas = document.createElement('canvas')
      canvas.width = 64
      canvas.height = 64
      const ctx = canvas.getContext('2d')
      if (!ctx) return null

      ctx.fillStyle = '#ffffff'
      ctx.font = 'bold 48px "Courier New", monospace'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(char, 32, 32)

      const texture = new THREE.CanvasTexture(canvas)
      texture.needsUpdate = true
      return texture
    }

    // Create particles
    const geometry = new THREE.PlaneGeometry(0.5, 0.5)
    for (let i = 0; i < particleCount; i++) {
      const char = chars[Math.floor(Math.random() * chars.length)]
      const texture = createCharTexture(char)

      if (texture) {
        // Randomize opacity and glow for spatial depth
        const opacity = 0.1 + Math.random() * 0.4
        const emissiveIntensity = Math.random() * 0.6

        const material = new THREE.MeshStandardMaterial({
          map: texture,
          transparent: true,
          opacity: opacity,
          color: 0xffffff,
          emissive: getColor(),
          emissiveIntensity: emissiveIntensity,
          side: THREE.DoubleSide,
          metalness: 0.1,
          roughness: 0.8
        })

        const particle = new THREE.Mesh(geometry, material)

        // Distribute particles in a tunnel formation around camera
        const angle = Math.random() * Math.PI * 2
        const radius = 5 + Math.random() * 15
        particle.position.x = Math.cos(angle) * radius
        particle.position.y = Math.sin(angle) * radius
        particle.position.z = Math.random() * -100

        // Random rotation
        particle.rotation.z = Math.random() * Math.PI * 2

        // Store speed for animation - slower
        ;(particle as any).speedZ = 0.05 + Math.random() * 0.1
        ;(particle as any).speedRotation = (Math.random() - 0.5) * 0.01
        ;(particle as any).charIndex = Math.floor(Math.random() * chars.length)
        ;(particle as any).changeTimer = 0

        particlesRef.current.push(particle)
        scene.add(particle)
      }
    }

    // Animation
    let lastColorUpdate = 0
    const animate = () => {
      if (!sceneRef.current || !cameraRef.current || !rendererRef.current) return

      animationIdRef.current = requestAnimationFrame(animate)

      // Update colors periodically
      const now = Date.now()
      if (now - lastColorUpdate > 1000) {
        lastColorUpdate = now
        const currentColor = getColor()
        particlesRef.current.forEach((particle) => {
          const material = particle.material as THREE.MeshStandardMaterial
          material.emissive.copy(currentColor)
        })
        // Update light color
        mainLight.color.copy(currentColor)
      }

      // Natural camera movement with easing
      const time = Date.now() * 0.0001
      const baseSpeed = 0.001
      const drift = Math.sin(time * 0.3) * 0.0005
      cameraRef.current.position.z -= baseSpeed + drift

      // Subtle camera sway
      cameraRef.current.position.x = Math.sin(time * 0.5) * 0.5
      cameraRef.current.position.y = Math.cos(time * 0.3) * 0.3

      // Update particles
      particlesRef.current.forEach((particle) => {
        // Move particle towards camera
        particle.position.z += (particle as any).speedZ

        // Rotate particle
        particle.rotation.z += (particle as any).speedRotation

        // Reset particle when it passes camera
        if (particle.position.z > cameraRef.current.position.z + 5) {
          particle.position.z = cameraRef.current.position.z - 100

          // Randomize position around tunnel
          const angle = Math.random() * Math.PI * 2
          const radius = 5 + Math.random() * 15
          particle.position.x = Math.cos(angle) * radius
          particle.position.y = Math.sin(angle) * radius

          // Change character occasionally
          ;(particle as any).changeTimer++
          if ((particle as any).changeTimer > 5) {
            ;(particle as any).changeTimer = 0
            const newChar = chars[Math.floor(Math.random() * chars.length)]
            const newTexture = createCharTexture(newChar)
            if (newTexture) {
              const material = particle.material as THREE.MeshStandardMaterial
              material.map?.dispose()
              material.map = newTexture
              material.needsUpdate = true
            }
          }
        }

        // Keep constant brightness
      })

      rendererRef.current.render(sceneRef.current, cameraRef.current)
    }

    // Start animation
    animate()
    console.log('AnimatedBackground: Animation started')

    // Handle resize
    const handleResize = () => {
      if (!containerRef.current || !cameraRef.current || !rendererRef.current) return
      cameraRef.current.aspect = window.innerWidth / containerRef.current.offsetHeight
      cameraRef.current.updateProjectionMatrix()
      rendererRef.current.setSize(window.innerWidth, containerRef.current.offsetHeight)
    }
    window.addEventListener('resize', handleResize)

    // Return cleanup function
    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [])

  useEffect(() => {
    // Initialize on mount
    init()

    // Cleanup on unmount
    return () => {
      console.log('AnimatedBackground: Component unmounting, cleaning up')
      if (animationIdRef.current !== null) {
        cancelAnimationFrame(animationIdRef.current)
        animationIdRef.current = null
      }
    }
  }, [init])

  return (
    <div ref={containerRef} className="absolute inset-0 overflow-hidden pointer-events-none">
      {/* Vignette effect */}
      <div className="absolute inset-0 bg-gradient-radial from-transparent via-transparent to-background/60" />
      {/* Bottom fade to prevent clipping */}
      <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-background to-transparent" />
    </div>
  )
}
