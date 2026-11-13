export function factTargets(profile, path='') {
  if (typeof profile === 'string') return [{path,value:profile}];
  if (!profile || typeof profile !== 'object') return [];
  return Object.entries(profile).flatMap(([key,value]) => key === 'work_preferences' && path === '' ? []
    : factTargets(value,`${path}/${key.replaceAll('~','~0').replaceAll('/','~1')}`));
}

export async function stringHash(value, engine=globalThis.crypto) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  return [...new Uint8Array(await engine.subtle.digest('SHA-256',bytes))].map(n=>n.toString(16).padStart(2,'0')).join('');
}
