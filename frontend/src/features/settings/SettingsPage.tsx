import { useCallback } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from '../../api';
import { useResource } from '../../hooks/useResource';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
export function SettingsPage() {
  const load = useCallback((signal: AbortSignal) => api.runtime(signal), []);
  const resource = useResource('runtime', load);
  const runtime = resource.data;
  return (
    <section className="panel management-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">LOCAL RUNTIME</span>
          <h1>运行环境</h1>
          <p className="muted">只读运行信息。配置与凭据由运营方管理，网页不写入环境路径或密钥。</p>
        </div>
        <button type="button" onClick={resource.reload}>
          <RefreshCw size={16} />
          刷新
        </button>
      </header>
      {resource.error ? (
        <ErrorNotice error={resource.error} onRetry={resource.reload} />
      ) : resource.loading && !runtime ? (
        <Loading />
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
            <p>
              ADMET 预测：<span className="badge unknown">未接入</span>
            </p>
            <p>
              智能摘要：<span className="badge unknown">未接入</span>
            </p>
            <p className="muted">本前端没有预测或摘要实现，不展示推测的活性、ADMET 或模型结论。</p>
          </section>
        </div>
      ) : (
        <Empty title="运行信息尚未提供" description="连接本地 API 后重新加载。" />
      )}
    </section>
  );
}
