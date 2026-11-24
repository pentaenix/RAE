import { Euler, PerspectiveCamera, Vector3 } from 'three';

const MOVEMENT = new Set([
  'KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE', 'ShiftLeft', 'ShiftRight',
]);

export class FreeCamera {
  constructor(canvas, help) {
    this.camera = new PerspectiveCamera(60, 1, 0.1, 10000);
    this.canvas = canvas;
    this.help = help;
    this.keys = new Set();
    this.rotation = new Euler(0, 0, 0, 'YXZ');
    this.motion = new Vector3();
    this.direction = new Vector3();
    this.start = new Vector3();
    this.target = new Vector3();
    this.active = false;
    this.drag = null;

    canvas.addEventListener('keydown', (event) => {
      if (!this.active) return;
      if (event.code === 'KeyR') this.reset();
      else if (event.code === 'Escape') canvas.blur();
      else if (MOVEMENT.has(event.code)) this.keys.add(event.code);
      else return;
      event.preventDefault();
    });
    canvas.addEventListener('keyup', (event) => this.keys.delete(event.code));
    canvas.addEventListener('blur', () => this.releaseInput());
    window.addEventListener('blur', () => this.releaseInput());
    document.addEventListener('visibilitychange', () => this.releaseInput());

    canvas.addEventListener('pointerdown', (event) => {
      if (!this.active || event.button !== 0) return;
      canvas.focus();
      canvas.setPointerCapture(event.pointerId);
      this.drag = { id: event.pointerId, x: event.clientX, y: event.clientY };
      event.preventDefault();
    });
    canvas.addEventListener('pointermove', (event) => {
      if (this.drag?.id !== event.pointerId) return;
      this.rotation.y -= (event.clientX - this.drag.x) * 0.004;
      const pitch = this.rotation.x - (event.clientY - this.drag.y) * 0.004;
      this.rotation.x = Math.max(-1.54, Math.min(1.54, pitch));
      this.camera.quaternion.setFromEuler(this.rotation);
      this.drag.x = event.clientX;
      this.drag.y = event.clientY;
    });
    canvas.addEventListener('lostpointercapture', (event) => {
      if (this.drag?.id === event.pointerId) this.drag = null;
    });
  }

  activate(settings, center, extent) {
    this.active = true;
    this.background = settings.background;
    this.start.fromArray(settings.start).sub(center);
    this.target.fromArray(settings.target).sub(center);
    this.camera.near = Math.max(0.01, extent / 10000);
    this.camera.far = extent * 12;
    this.camera.updateProjectionMatrix();
    this.speed = extent * 0.065;
    this.canvas.tabIndex = 0;
    this.help.hidden = false;
    this.reset();
  }

  deactivate() {
    if (!this.active) return;
    this.releaseInput();
    this.active = false;
    this.background = undefined;
    this.canvas.removeAttribute('tabindex');
    this.help.hidden = true;
  }

  releaseInput() {
    this.keys.clear();
    const drag = this.drag;
    this.drag = null;
    if (drag && this.canvas.hasPointerCapture(drag.id)) this.canvas.releasePointerCapture(drag.id);
  }

  reset() {
    this.camera.position.copy(this.start);
    this.camera.lookAt(this.target);
    this.rotation.setFromQuaternion(this.camera.quaternion, 'YXZ');
    this.lastFrame = undefined;
  }

  update(now, width, height) {
    const aspect = width / Math.max(height, 1);
    if (aspect > 0 && aspect !== this.camera.aspect) {
      this.camera.aspect = aspect;
      this.camera.updateProjectionMatrix();
    }
    const dt = Math.min((now - (this.lastFrame ?? now)) / 1000, 0.05);
    this.lastFrame = now;
    const axis = (positive, negative) => Number(this.keys.has(positive)) - Number(this.keys.has(negative));
    this.motion.set(0, 0, axis('KeyS', 'KeyW')).applyQuaternion(this.camera.quaternion);
    this.direction.set(axis('KeyD', 'KeyA'), 0, 0).applyQuaternion(this.camera.quaternion);
    this.motion.add(this.direction);
    this.motion.y += axis('KeyE', 'KeyQ');
    if (this.motion.lengthSq() > 1) this.motion.normalize();
    const fast = this.keys.has('ShiftLeft') || this.keys.has('ShiftRight');
    this.camera.position.addScaledVector(this.motion, this.speed * dt * (fast ? 3 : 1));
  }
}
