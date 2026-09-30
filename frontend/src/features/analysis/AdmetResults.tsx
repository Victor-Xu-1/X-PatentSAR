import type { AdmetResult } from '../../api/analysisTypes';
import { dateText } from '../../model/presentation';
export function AdmetResults({ result }: { result: AdmetResult }) {
  return (
    <section className="admet-results" aria-label="本地 ADMET 分析结果" aria-live="polite">
      <p className="analysis-provenance">
        {result.engine.name} · {result.engine.version} · {dateText(result.generated_at)}
      </p>
      <details>
        <summary>模型来源 SHA-256</summary>
        <code className="break-word">{result.engine.model_sha256}</code>
      </details>
      {result.warnings.length > 0 && (
        <ul className="analysis-warnings">
          {result.warnings.map((warning, i) => (
            <li key={i}>{warning}</li>
          ))}
        </ul>
      )}
      {result.predictions.map((prediction, i) => (
        <section key={i} className="molecule-result">
          <h3>分子 {i + 1}</h3>
          <code className="break-word">{prediction.smiles}</code>
          <div className="analysis-table-scroll">
            <table className="analysis-table">
              <caption className="sr-only">分子 {i + 1} 描述符与模型端点</caption>
              <thead>
                <tr>
                  <th>属性 / 端点</th>
                  <th>数值</th>
                  <th>单位</th>
                  <th>来源</th>
                </tr>
              </thead>
              <tbody>
                {prediction.properties.map((property, index) => (
                  <tr key={`${property.key}-${index}`}>
                    <th scope="row" title={property.key}>
                      {property.label || property.key}
                    </th>
                    <td>{String(property.value)}</td>
                    <td>{property.unit ?? '未提供'}</td>
                    <td>{property.kind === 'descriptor' ? 'RDKit 描述符' : '模型预测'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </section>
  );
}
