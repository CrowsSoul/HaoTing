<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { BBox, Finding, ModelBundle, DisplayMesh } from './generated/contracts'
const props = defineProps<{ model: ModelBundle | null; finding: Finding | null; mesh: DisplayMesh | null }>()
const host = ref<HTMLDivElement>()
const error = ref('')
let renderer: THREE.WebGLRenderer | undefined
let controls: OrbitControls | undefined
let observer: ResizeObserver | undefined
let frame = 0
const scene = new THREE.Scene()
scene.background = new THREE.Color('#eef4f5')
const group = new THREE.Group()
scene.add(group)
const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 1e7)
camera.up.set(0,0,1)
scene.add(new THREE.AmbientLight('#ffffff', 2))
const light = new THREE.DirectionalLight('#ffffff', 3); light.position.set(1,2,3); scene.add(light)
let scale = 20
function box(b: BBox, color: string, fill: boolean) {
  const size = [b.xmax - b.xmin, b.ymax - b.ymin, b.zmax - b.zmin].map(x => Math.max(x, scale * 0.002))
  const geo = new THREE.BoxGeometry(size[0], size[1], size[2])
  const pos = [(b.xmin+b.xmax)/2, (b.ymin+b.ymax)/2, (b.zmin+b.zmax)/2]
  if (fill) {
    const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.09, depthWrite: false }))
    mesh.position.set(...pos as [number, number, number]); group.add(mesh)
  }
  const line = new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color }))
  line.position.set(...pos as [number, number, number]); group.add(line)
  geo.dispose()
}
function disposeGroup() {
  for (const obj of [...group.children]) {
    group.remove(obj)
    if ('geometry' in obj) (obj.geometry as THREE.BufferGeometry).dispose()
    if ('material' in obj) {
      const materials = obj.material as THREE.Material | THREE.Material[]
      ;(Array.isArray(materials) ? materials : [materials]).forEach(m => m.dispose())
    }
  }
}
function fit() {
  const bounds = new THREE.Box3().setFromObject(group)
  if (bounds.isEmpty()) return
  const center = bounds.getCenter(new THREE.Vector3())
  scale = Math.max(bounds.getSize(new THREE.Vector3()).length(), 1)
  const distance = scale * 1.7 / Math.min(camera.aspect, 1)
  camera.position.copy(center).add(new THREE.Vector3(distance, distance * .7, distance))
  camera.near = scale / 10000; camera.far = distance * 100; camera.updateProjectionMatrix()
  controls?.target.copy(center); controls?.update()
}
function draw() {
  disposeGroup()
  const parts = props.model?.parts ?? []
  const union = new THREE.Box3()
  for (const p of parts) if (p.bbox) {
    const b = p.bbox
    union.expandByPoint(new THREE.Vector3(b.xmin,b.ymin,b.zmin)); union.expandByPoint(new THREE.Vector3(b.xmax,b.ymax,b.zmax))
  }
  scale = Math.max(union.isEmpty() ? 20 : union.getSize(new THREE.Vector3()).length(), 1)
  if (props.mesh) {
    const positions: number[] = [], colors: number[] = []
    const selected = new Set(props.finding?.evidence.face_ids ?? [])
    props.mesh.triangles.forEach((tri,i) => {
      const color = new THREE.Color(selected.has(props.mesh!.face_ids[i]) ? '#e45143' : '#8aa9b2')
      for (const index of tri) {
        positions.push(...props.mesh!.vertices[index]); colors.push(color.r,color.g,color.b)
      }
    })
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3))
    geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3)); geometry.computeVertexNormals()
    group.add(new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({vertexColors:true,side:THREE.DoubleSide,roughness:.65})))
  } else parts.forEach(p => { if (p.bbox) box(p.bbox, '#6a929c', true) })
  const f = props.finding
  if (f) {
    const ids = new Set(f.evidence.face_ids)
    if (!props.mesh) {
      props.model?.faces.filter(face => ids.has(face.face_id)).forEach(face => { if (face.bbox) box(face.bbox, '#e45143', true) })
      if (f.bbox) box(f.bbox, '#e45143', false)
    }
    if (f.location) {
      const point = new THREE.Mesh(new THREE.SphereGeometry(scale * .014, 18, 12), new THREE.MeshBasicMaterial({ color: '#e45143', depthTest: false }))
      point.position.set(...f.location); point.renderOrder=2; group.add(point)
    }
    if (f.path_points.length > 1) {
      const geometry = new THREE.BufferGeometry().setFromPoints(f.path_points.map(p => new THREE.Vector3(...p)))
      group.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: '#e45143', depthTest: false })))
    }
  }
  fit()
}
onMounted(() => {
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    host.value!.appendChild(renderer.domElement)
    controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true
    observer = new ResizeObserver(() => {
      const { clientWidth: w, clientHeight: h } = host.value!
      renderer!.setSize(w, h); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix(); fit()
    })
    observer.observe(host.value!)
    draw()
    const animate = () => { frame = requestAnimationFrame(animate); controls?.update(); renderer?.render(scene, camera) }
    animate()
  } catch { error.value = '当前浏览器无法启用 3D，请在下方查看面 ID、坐标和缺陷详情。' }
})
watch(() => [props.model, props.finding, props.mesh], draw)
onBeforeUnmount(() => { cancelAnimationFrame(frame); observer?.disconnect(); controls?.dispose(); disposeGroup(); renderer?.dispose() })
</script>
<template>
  <div class="viewer-shell"><div ref="host" class="viewer"></div>
    <div class="viewer-note">{{ mesh?'面 ID 网格 · 精确高亮':'区域定位 · 包围盒示意' }} <span>{{ model?.units ?? 'mm' }}</span></div>
    <button class="viewer-fit quiet" @click="fit">适应视图</button>
    <div v-if="error || !model" class="viewer-empty">{{ error || '检查完成后显示模型区域' }}</div>
    <div class="viewer-legend"><i></i> 零件区域 <i class="red"></i> 选中缺陷 · 拖动旋转 / 滚轮缩放</div>
  </div>
</template>
