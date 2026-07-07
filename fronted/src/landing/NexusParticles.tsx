import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

if (typeof window !== 'undefined') {
  gsap.registerPlugin(ScrollTrigger)
}

/**
 * NexusParticles — the WebGL embodiment of the dividing line.
 *
 * A field of ~6,000 points. On the left they hold a rigid lattice — the
 * machine: cold, ordered, electric blue. Crossing the center they loosen into
 * an organic, breathing wave — the human hand: warm-teal, fluid, alive.
 * Scroll scrubs the field awake (uMix) via an internal ScrollTrigger bound to
 * the parent section.
 *
 * Guardrails: DPR capped at 1.75, rAF paused when off-screen
 * (IntersectionObserver), full dispose on unmount, reduced-motion renders a
 * single static frame with no loop.
 */

const COLS = 130
const ROWS = 46
const SPAN_X = 17
const SPAN_Y = 6.2

const VERT = /* glsl */ `
  uniform float uTime;
  uniform float uMix;
  attribute float aSide; // 0 = machine (left), 1 = human (right)
  varying float vSide;
  varying float vFade;

  void main() {
    vSide = aSide;
    vec3 p = position;

    // Machine: rigid plane with a faint scanning pulse along the lattice.
    float machineZ = 0.06 * sin(uTime * 1.2 + p.x * 4.0) * step(0.985, sin(p.y * 40.0));

    // Human: layered organic swell.
    float humanZ =
        0.55 * sin(p.x * 1.15 + uTime * 0.85) * cos(p.y * 1.4 + uTime * 0.6)
      + 0.22 * sin(p.x * 2.6 - uTime * 0.5 + p.y * 1.9);

    p.z = mix(machineZ, humanZ, aSide) * uMix;
    p.y += aSide * 0.14 * sin(uTime * 0.7 + p.x * 0.9) * uMix;

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = (2.0 + aSide * 2.2 + p.z * 1.4) * (28.0 / -mv.z);
    vFade = uMix;
  }
`

const FRAG = /* glsl */ `
  precision mediump float;
  varying float vSide;
  varying float vFade;

  void main() {
    vec2 uv = gl_PointCoord - 0.5;
    float d = length(uv);
    float alpha = smoothstep(0.5, 0.08, d);

    vec3 machine = vec3(0.231, 0.510, 0.965); // #3b82f6 electric
    vec3 human   = vec3(0.176, 0.831, 0.749); // #2dd4bf teal
    vec3 color = mix(machine, human, vSide);

    gl_FragColor = vec4(color, alpha * (0.28 + 0.62 * vFade));
  }
`

export function NexusParticles({ className = '' }: { className?: string }) {
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: 'low-power' })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75))
    renderer.setClearColor(0x000000, 0)
    host.appendChild(renderer.domElement)
    renderer.domElement.style.position = 'absolute'
    renderer.domElement.style.inset = '0'
    renderer.domElement.style.width = '100%'
    renderer.domElement.style.height = '100%'

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(46, 1, 0.1, 60)
    camera.position.set(0, -2.6, 7.2)
    camera.lookAt(0, 0, 0)

    // Grid of points with a per-point machine/human blend factor.
    const count = COLS * ROWS
    const positions = new Float32Array(count * 3)
    const sides = new Float32Array(count)
    let i = 0
    for (let cx = 0; cx < COLS; cx++) {
      for (let cy = 0; cy < ROWS; cy++) {
        const x = (cx / (COLS - 1) - 0.5) * SPAN_X
        const y = (cy / (ROWS - 1) - 0.5) * SPAN_Y
        positions[i * 3] = x
        positions[i * 3 + 1] = y
        positions[i * 3 + 2] = 0
        // The dividing line: smooth hand-off across the center third.
        const t = (x / SPAN_X + 0.5) // 0..1 across the field
        sides[i] = Math.min(1, Math.max(0, (t - 0.38) / 0.24))
        i++
      }
    }
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geometry.setAttribute('aSide', new THREE.BufferAttribute(sides, 1))

    const material = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: {
        uTime: { value: 0 },
        uMix: { value: reduced ? 1 : 0 },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })

    const points = new THREE.Points(geometry, material)
    points.rotation.x = -0.42
    scene.add(points)

    const resize = () => {
      const w = host.clientWidth || 1
      const h = host.clientHeight || 1
      renderer.setSize(w, h, false)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(host)

    // Scroll drives the field awake across the parent section.
    let trigger: ScrollTrigger | null = null
    if (!reduced) {
      trigger = ScrollTrigger.create({
        trigger: host.parentElement ?? host,
        start: 'top 85%',
        end: 'bottom 20%',
        scrub: 0.6,
        onUpdate: (self) => {
          // Ramp in over the first 40% of the section, then hold.
          material.uniforms.uMix.value = Math.min(1, self.progress / 0.4)
          points.rotation.z = (self.progress - 0.5) * 0.14
        },
      })
    }

    // rAF loop — paused off-screen.
    let raf = 0
    let visible = true
    const clock = new THREE.Clock()
    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      if (visible && !reduced) loop()
    })
    io.observe(host)

    const loop = () => {
      if (!visible) return
      material.uniforms.uTime.value = clock.getElapsedTime()
      renderer.render(scene, camera)
      raf = requestAnimationFrame(loop)
    }

    if (reduced) {
      // One honest static frame.
      material.uniforms.uTime.value = 2.4
      renderer.render(scene, camera)
    } else {
      loop()
    }

    return () => {
      cancelAnimationFrame(raf)
      io.disconnect()
      ro.disconnect()
      trigger?.kill()
      geometry.dispose()
      material.dispose()
      renderer.dispose()
      host.removeChild(renderer.domElement)
    }
  }, [])

  return <div ref={hostRef} className={`pointer-events-none absolute inset-0 ${className}`} aria-hidden />
}
