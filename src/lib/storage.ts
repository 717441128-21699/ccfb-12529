/**
 * IndexedDB 本地存储：素材、课程包（清单+分片 blob）、课程密钥、学员、吊销表。
 * 所有数据不离开浏览器；导出 .cpkg / .lic 是唯一的跨设备交换方式。
 */

import { KeyRecord, MaterialRecord, PackageManifest, StudentRecord } from '../types';

const DB_NAME = 'courseguard';
const DB_VERSION = 1;

const STORES = {
  materials: 'materials',
  packages: 'packages', // 存 manifest（PackageManifest）
  segmentBlobs: 'segmentBlobs', // key: `${courseId}/${fileName}` → Uint8Array
  keys: 'keys',
  students: 'students',
  revocation: 'revocation', // key: courseId → { courseId, version, updatedAt }
} as const;

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORES.materials)) db.createObjectStore(STORES.materials, { keyPath: 'materialId' });
      if (!db.objectStoreNames.contains(STORES.packages)) db.createObjectStore(STORES.packages, { keyPath: 'courseId' });
      if (!db.objectStoreNames.contains(STORES.segmentBlobs)) db.createObjectStore(STORES.segmentBlobs);
      if (!db.objectStoreNames.contains(STORES.keys)) db.createObjectStore(STORES.keys, { keyPath: 'courseId' });
      if (!db.objectStoreNames.contains(STORES.students)) db.createObjectStore(STORES.students, { keyPath: 'studentId' });
      if (!db.objectStoreNames.contains(STORES.revocation)) db.createObjectStore(STORES.revocation, { keyPath: 'courseId' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

function tx<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(store, mode);
        const req = fn(t.objectStore(store));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      }),
  );
}

export async function idbPut<T>(store: string, value: T, key?: IDBValidKey): Promise<void> {
  await tx(store, 'readwrite', (s) => s.put(value as object, key));
}

export async function idbGet<T>(store: string, key: IDBValidKey): Promise<T | undefined> {
  return tx(store, 'readonly', (s) => s.get(key) as IDBRequest<T>);
}

export async function idbGetAll<T>(store: string): Promise<T[]> {
  return tx(store, 'readonly', (s) => s.getAll() as IDBRequest<T[]>);
}

export async function idbDelete(store: string, key: IDBValidKey): Promise<void> {
  await tx(store, 'readwrite', (s) => s.delete(key));
}

export async function idbAllKeys(store: string): Promise<IDBValidKey[]> {
  return tx(store, 'readonly', (s) => s.getAllKeys());
}

// ---------------- 业务封装 ----------------

export const storage = {
  // 素材
  listMaterials: () => idbGetAll<MaterialRecord>(STORES.materials),
  getMaterial: (id: string) => idbGet<MaterialRecord>(STORES.materials, id),
  putMaterial: (m: MaterialRecord) => idbPut(STORES.materials, m),
  deleteMaterial: (id: string) => idbDelete(STORES.materials, id),

  // 课程包
  listPackages: () => idbGetAll<PackageManifest>(STORES.packages),
  getPackage: (courseId: string) => idbGet<PackageManifest>(STORES.packages, courseId),
  putPackage: (m: PackageManifest) => idbPut(STORES.packages, m),
  deletePackage: async (courseId: string) => {
    const manifest = await idbGet<PackageManifest>(STORES.packages, courseId);
    if (manifest) {
      for (const seg of manifest.segments) await idbDelete(STORES.segmentBlobs, `${courseId}/${seg.fileName}`);
    }
    await idbDelete(STORES.packages, courseId);
  },
  putSegment: (courseId: string, fileName: string, bytes: Uint8Array) =>
    idbPut(STORES.segmentBlobs, bytes, `${courseId}/${fileName}`),
  getSegment: (courseId: string, fileName: string) =>
    idbGet<Uint8Array>(STORES.segmentBlobs, `${courseId}/${fileName}`),

  // 密钥
  listKeys: () => idbGetAll<KeyRecord>(STORES.keys),
  getKey: (courseId: string) => idbGet<KeyRecord>(STORES.keys, courseId),
  putKey: (k: KeyRecord) => idbPut(STORES.keys, k),

  // 学员
  listStudents: () => idbGetAll<StudentRecord>(STORES.students),
  getStudent: (id: string) => idbGet<StudentRecord>(STORES.students, id),
  putStudent: (s: StudentRecord) => idbPut(STORES.students, s),
  deleteStudent: (id: string) => idbDelete(STORES.students, id),

  // 吊销版本
  async getRevocation(courseId: string): Promise<number> {
    const rec = await idbGet<{ courseId: string; version: number }>(STORES.revocation, courseId);
    return rec?.version ?? 0;
  },
  async bumpRevocation(courseId: string): Promise<number> {
    const cur = await storage.getRevocation(courseId);
    const next = cur + 1;
    await idbPut(STORES.revocation, { courseId, version: next, updatedAt: Date.now() });
    return next;
  },
};

export { STORES };
