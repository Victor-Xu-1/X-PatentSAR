export type Decoder<T> = (input: unknown, path?: string) => T;
export class ContractError extends Error {
  constructor(path: string) {
    super(`API 数据格式不符合契约（${path}）。请联系服务维护者。`);
    this.name = 'ContractError';
  }
}
export const string: Decoder<string> = (v, p = '$') => {
  if (typeof v !== 'string') throw new ContractError(p);
  return v;
};
export const number: Decoder<number> = (v, p = '$') => {
  if (typeof v !== 'number' || !Number.isFinite(v)) throw new ContractError(p);
  return v;
};
export const boolean: Decoder<boolean> = (v, p = '$') => {
  if (typeof v !== 'boolean') throw new ContractError(p);
  return v;
};
export const count: Decoder<number> = (v, p = '$') => {
  const n = number(v, p);
  if (!Number.isSafeInteger(n) || n < 0) throw new ContractError(p);
  return n;
};
export const positive: Decoder<number> = (v, p = '$') => {
  const n = count(v, p);
  if (n < 1) throw new ContractError(p);
  return n;
};
export function nullable<T>(decode: Decoder<T>): Decoder<T | null> {
  return (v, p) => (v == null ? null : decode(v, p));
}
export function defaulted<T>(decode: Decoder<T>, fallback: T): Decoder<T> {
  return (v, p) => (v === undefined ? fallback : decode(v, p));
}
export function array<T>(decode: Decoder<T>): Decoder<T[]> {
  return (v, p = '$') => {
    if (!Array.isArray(v) || v.length > 100_000) throw new ContractError(p);
    return v.map((item, i) => decode(item, `${p}[${i}]`));
  };
}
export function oneOf<const T extends readonly string[]>(values: T): Decoder<T[number]> {
  return (v, p = '$') => {
    if (typeof v !== 'string' || !values.includes(v)) throw new ContractError(p);
    return v as T[number];
  };
}
export const scalar: Decoder<string | number> = (v, p) =>
  typeof v === 'string' ? string(v, p) : number(v, p);
export function object<T extends Record<string, Decoder<unknown>>>(
  shape: T,
): Decoder<{ [K in keyof T]: ReturnType<T[K]> }> {
  return (v, p = '$') => {
    if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new ContractError(p);
    const input = v as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(shape).map(([key, decode]) => [key, decode(input[key], `${p}.${key}`)]),
    ) as { [K in keyof T]: ReturnType<T[K]> };
  };
}
