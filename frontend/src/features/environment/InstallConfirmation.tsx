import { useState } from 'react';
import { Dialog } from '../../components/Dialog';
import type { EnvironmentComponent, EnvironmentSettings } from '../../api/environmentTypes';
import { environmentBytes } from '../../model/environment';
export interface InstallPlan {
  components: EnvironmentComponent[];
  settings: EnvironmentSettings;
}
export function InstallConfirmation({
  plan,
  currentRevision,
  busy,
  onClose,
  onConfirm,
}: {
  plan: InstallPlan;
  currentRevision: number;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const stale = currentRevision !== plan.settings.revision;
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
          服务端负责固定版本、来源与内容校验，以及验证后的配置应用；已有提取/分析操作保留各自捕获的配置。依赖由同一审核安装计划处理。
        </p>
        <ul className="installation-plan">
          {plan.components.map((component) => (
            <li key={component.id}>
              <strong>
                {component.name} · {component.version}
              </strong>
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
              ? '安装目录配置已变化，请关闭并重新确认。'
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
