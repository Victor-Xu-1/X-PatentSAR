import type { Runtime } from '../../api/types';
import type { Resource } from '../../hooks/useResource';
import { ErrorNotice, Loading } from '../../components/Feedback';
export function RuntimeDiagnostics({ resource }: { resource: Resource<Runtime> }) {
  const runtime = resource.data;
  return (
    <details className="panel environment-card runtime-diagnostics">
      <summary>运行诊断</summary>
      <p className="muted">保留本地运行信息；检测报告与配置应用不代替实际提取或模型推理验收。</p>
      {resource.error ? (
        <ErrorNotice error={resource.error} onRetry={resource.reload} />
      ) : resource.loading && !runtime ? (
        <Loading label="正在读取运行诊断…" />
      ) : runtime ? (
        <div className="settings-sections">
          <section>
            <h2>产品与存储</h2>
            <dl>
              <dt>产品</dt>
              <dd>{runtime.product.name}</dd>
              <dt>版本</dt>
              <dd>{runtime.product.version}</dd>
              <dt>运行平台</dt>
              <dd>{runtime.storage.platform}</dd>
              <dt>服务端状态目录</dt>
              <dd className="break-word">{runtime.storage.state_root}</dd>
            </dl>
          </section>
          <section>
            <h2>解释器可用性</h2>
            {runtime.interpreters.length ? (
              <table className="runtime-table">
                <thead>
                  <tr>
                    <th>角色</th>
                    <th>已配置</th>
                    <th>可用性</th>
                  </tr>
                </thead>
                <tbody>
                  {runtime.interpreters.map((interpreter) => (
                    <tr key={interpreter.role}>
                      <td>{interpreter.role}</td>
                      <td>{interpreter.configured ? '已配置' : '未配置'}</td>
                      <td>
                        <span className={`badge ${interpreter.available ? 'high' : 'review'}`}>
                          {interpreter.available ? '可用' : '不可用'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">服务端未报告解释器。</p>
            )}
          </section>
          <section>
            <h2>能力边界</h2>
            <p>本地 ADMET：{runtime.capabilities.admet ? '服务报告可用' : '环境不可用'}</p>
            <p>确定性证据摘要：{runtime.capabilities.summary ? '服务报告可用' : '环境不可用'}</p>
            <p className="muted">
              组件安装不会修改专利产物、绑定、人工复核或正式 QA。证据摘要是确定性统计，不是 LLM。
            </p>
          </section>
        </div>
      ) : (
        <p className="info-banner">运行信息尚未提供。</p>
      )}
    </details>
  );
}
