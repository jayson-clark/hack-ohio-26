// WebGL renderer lifecycle shared by the flat and 3D views: canvas, resize,
// and an animation loop that stops when the view unmounts.

import * as THREE from "three";

export interface Viewport {
  renderer: THREE.WebGLRenderer;
  dispose(): void;
}

export function mountViewport(
  container: HTMLElement,
  onResize: (width: number, height: number) => void,
  onFrame: (timeSec: number) => void,
): Viewport {
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.domElement.style.display = "block";
  renderer.domElement.style.width = "100%";
  renderer.domElement.style.height = "100%";
  container.appendChild(renderer.domElement);

  const resize = () => {
    const w = Math.max(1, container.clientWidth);
    const h = Math.max(1, container.clientHeight);
    renderer.setSize(w, h, false);
    onResize(w, h);
  };
  const observer = new ResizeObserver(resize);
  observer.observe(container);
  resize();

  const start = performance.now();
  renderer.setAnimationLoop(() => onFrame((performance.now() - start) / 1000));

  return {
    renderer,
    dispose() {
      renderer.setAnimationLoop(null);
      observer.disconnect();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}
