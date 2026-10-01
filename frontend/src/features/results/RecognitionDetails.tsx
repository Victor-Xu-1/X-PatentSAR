import type { CompoundRecognition } from '../../api/types';
import { recognitionText } from '../../model/results';

export function RecognitionStatus({ recognition }: { recognition: CompoundRecognition | null }) {
  return (
    <span
      className={`badge recognition-${recognition?.status ?? 'unknown'}`}
      title={recognition?.quality_flag ?? 'RDKit 可解析不代表结构与原图一致'}
    >
      {recognitionText(recognition)}
    </span>
  );
}

export function RecognitionDetails({ recognition }: { recognition: CompoundRecognition | null }) {
  return (
    <section className="recognition-details" aria-label="识别质量与模型观察">
      <h3>识别校验（RDKit）</h3>
      <RecognitionStatus recognition={recognition} />
      <dl>
        <dt>质量标记</dt>
        <dd>{recognition?.quality_flag ?? '未提供'}</dd>
        <dt>模型指纹</dt>
        <dd>{recognition?.model_fingerprint ?? '未提供'}</dd>
      </dl>
      {recognition?.token_confidence ? (
        <p>
          模型 token confidence（未校准）：最小值 {recognition.token_confidence.minimum} · 均值{' '}
          {recognition.token_confidence.mean}
        </p>
      ) : (
        <p className="muted">模型 token confidence 未提供</p>
      )}
      <p className="muted">
        token confidence 未校准，不是结构正确率，也不是人工复核结论。RDKit
        可解析仅证明字符串可被解析，不证明识别结构与原图一致。
      </p>
    </section>
  );
}
