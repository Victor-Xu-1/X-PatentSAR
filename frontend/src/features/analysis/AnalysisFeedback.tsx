import { ErrorNotice, Loading } from '../../components/Feedback';
export function AnalysisFeedback({
  busy,
  error,
  uncertain,
  remainingSeconds,
  acknowledge,
  pendingLabel,
}: {
  busy: boolean;
  error: Error | null;
  uncertain: boolean;
  remainingSeconds: number | null;
  acknowledge: () => void;
  pendingLabel: string;
}) {
  return (
    <>
      {busy && (
        <>
          <Loading label={pendingLabel} />
          <output className="analysis-provenance">
            本地推理与 QC 最长 180 秒；本页面有界等待 190 秒（剩余最多 {remainingSeconds ?? 0}{' '}
            秒）。请等待，关闭弹窗暂时锁定；前端停止等待不代表后台已取消，清理由服务端 timeout/close
            负责。
          </output>
        </>
      )}
      {error && <ErrorNotice error={error} />}
      {uncertain && (
        <div className="info-banner">
          <output>
            本次分析结果未知，不可视为已失败或已取消；禁止盲目重放。等待服务端执行边界结束，再确认环境状态后手动重试。剩余等待边界：
            {remainingSeconds ?? 0} 秒。
          </output>
          <button type="button" disabled={remainingSeconds !== 0} onClick={acknowledge}>
            已等待边界，重新允许手动分析
          </button>
        </div>
      )}
    </>
  );
}
