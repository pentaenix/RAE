import { ShaderChunk, SRGBColorSpace } from 'three';

const SHADER_MAPS = {
  color: 'snapLayerColor',
  normal: 'snapLayerNormal',
  emissive: 'snapLayerEmissive',
};

function installShader(material, layers) {
  const names = Object.keys(layers);
  material.customProgramCacheKey = () => `snap-layers:${names.join(',')}`;
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = `attribute float _snap_layer_mask;
      varying float vSnapLayerMask;
      ${shader.vertexShader.replace('#include <uv_vertex>', '#include <uv_vertex>\nvSnapLayerMask = _snap_layer_mask;')}`;
    const declarations = ['varying float vSnapLayerMask;'];
    for (const name of names) {
      const uniform = SHADER_MAPS[name];
      shader.uniforms[uniform] = { value: layers[name] };
      declarations.push(`uniform sampler2D ${uniform};`);
    }
    let fragment = shader.fragmentShader;
    if (layers.color) {
      const map = ShaderChunk.map_fragment.replace(
        'diffuseColor *= sampledDiffuseColor;',
        `sampledDiffuseColor.rgb = mix(sampledDiffuseColor.rgb,
          texture2D(snapLayerColor, vMapUv).rgb, vSnapLayerMask);
        diffuseColor *= sampledDiffuseColor;`,
      );
      fragment = fragment.replace('#include <map_fragment>', map);
    }
    if (layers.normal) {
      const map = ShaderChunk.normal_fragment_maps.replace(
        'mapN.xy *= normalScale;',
        `vec3 layerN = texture2D(snapLayerNormal, vNormalMapUv).xyz * 2.0 - 1.0;
        mapN = mix(mapN, layerN, vSnapLayerMask);
        mapN.xy *= normalScale;`,
      );
      fragment = fragment.replace('#include <normal_fragment_maps>', map);
    }
    if (layers.emissive) {
      fragment = fragment.replace(
        '#include <emissivemap_fragment>',
        `#include <emissivemap_fragment>
        totalEmissiveRadiance = mix(totalEmissiveRadiance,
          texture2D(snapLayerEmissive, vMapUv).rgb * vec3(0.33, 0.42, 0.55), vSnapLayerMask);`,
      );
    }
    shader.fragmentShader = `${declarations.join('\n')}\n${fragment}`;
  };
  const disposeLayers = () => {
    for (const texture of Object.values(layers)) texture.dispose();
    material.removeEventListener('dispose', disposeLayers);
  };
  material.addEventListener('dispose', disposeLayers);
}

export function registerGlbLoaderPlugins(loader) {
  loader.register((parser) => ({
    name: 'RAE_snap_preview_layers',
    async afterRoot({ scene }) {
      const jobs = new Map();
      scene.traverse((mesh) => {
        if (!mesh.isMesh || !mesh.geometry.hasAttribute('_snap_layer_mask')) return;
        const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        for (const material of materials) {
          if (jobs.has(material)) continue;
          const index = parser.associations.get(material)?.materials;
          const source = parser.json.materials?.[index]?.extras?.rae?.snapLayers;
          if (!source) continue;
          jobs.set(material, Promise.all(Object.keys(SHADER_MAPS).filter(
            (name) => Number.isInteger(source[name]),
          ).map(async (name) => {
            const texture = (await parser.getDependency('texture', source[name])).clone();
            if (name !== 'normal') texture.colorSpace = SRGBColorSpace;
            return [name, texture];
          })).then((layers) => installShader(material, Object.fromEntries(layers))));
        }
      });
      await Promise.all(jobs.values());
    },
  }));
}
