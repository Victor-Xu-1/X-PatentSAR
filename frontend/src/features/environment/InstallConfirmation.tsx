import { useState } from 'react';
import { Dialog } from '../../components/Dialog';
import type {
  EnvironmentComponent,
  EnvironmentComponentId,
  EnvironmentSettings,
} from '../../api/environmentTypes';
import { environmentBytes } from '../../model/environment';
import {
  environmentComponentBadge,
  isEnvironmentComponentReady,
} from '../../model/environmentStatus';
export interface InstallPlan {
  components: EnvironmentComponent[];
  settings: EnvironmentSettings;
  requested: EnvironmentComponentId[];
}
export function InstallConfirmation({
  plan,
  currentRevision,
  planCurrent,
  busy,
  onClose,
  onConfirm,
}: {
  plan: InstallPlan;
  currentRevision: number;
  planCurrent: boolean;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const configurationChanged = currentRevision !== plan.settings.revision;
  const stale = configurationChanged || !planCurrent;
  const missingLicense = plan.components.some((component) => !component.license.trim());
  return (
    <Dialog title="确认环境安装" onClose={onClose} busy={busy} wide>
      <div className="dialog-body">
        <p>
          将创建持久化后台操作，在{' '}
          <strong className="break-word">{plan.settings.install_root}</strong> 安装审核的 CPU
          组件。可能下载较大文件；不安装 GPU / CUDA，不调用付费服务，不覆盖未知已有环境。
        </p>
        <p className="muted">
          下方包括所选组件与服务端声明的全部前置依赖，确认后将提交完全相同的组件集合。已可用的前置依赖仍列出核对，由后端验证能否复用；不推测额外组件或隐藏
          SDK 下载。
        </p>
        <p className="muted">
          下载大小按服务端报告逐项展示，未报告不视为零；实际下载可能因已验证缓存而减少。服务端负责来源校验与验证后配置应用，已有提取/分析操作保留捕获的配置。
        </p>
        <ul className="installation-plan">
          {plan.components.map((component) => (
            <li key={component.id} data-install-component={component.id}>
              <strong>
                {component.name} · 目标版本 {component.version}
              </strong>
              <small>{plan.requested.includes(component.id) ? '所选组件' : '前置依赖'}</small>
              <small>
                {isEnvironmentComponentReady(component)
                  ? '已安装·已验证；后端复验后复用'
                  : environmentComponentBadge(component).label}
              </small>
              <span>
                下载：{environmentBytes(component.download_bytes)} · 许可证：
                {component.license || '未报告'}
              </span>
              <small className="break-word">来源：{component.source_url || '未报告'}</small>
            </li>
          ))}
        </ul>
        {(stale || missingLicense) && (
          <p className="error-notice">
            {stale
              ? configurationChanged
                ? '安装目录配置已变化，请关闭并重新确认。'
                : '组件状态或依赖计划已变化，请关闭并重新确认；不重复安装已有组件。'
              : '服务端未提供完整许可证信息，不能确认安装。'}
          </p>
        )}
        <label className="option-check">
          <input
            data-initial-focus
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            disabled={busy || stale || missingLicense}
          />
          我已确认安装目录、CPU 下载范围及上述许可证
        </label>
        <footer className="dialog-actions">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="primary"
            disabled={!confirmed || busy || stale || missingLicense}
            onClick={() => void onConfirm()}
          >
            {busy ? '正在提交后台操作…' : '确认下载并安装'}
          </button>
        </footer>
      </div>
    </Dialog>
  );
}
