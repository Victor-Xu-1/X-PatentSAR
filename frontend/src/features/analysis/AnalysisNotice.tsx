export function AnalysisNotice({ available }: { available?: boolean | null }) {
  return (
    <div className="analysis-notice">
      <p>
        本地独立分析仅供复核，不改变正式提取、绑定、SMILES、置信度或 QA
        验收；分子不会上传到远程服务。
      </p>
      {available === false && (
        <p>
          服务报告此能力当前不可用。仍可输入分子或识别裁图；请求失败会显示实际错误，不生成替代预测。
        </p>
      )}
      <a className="link-button" href="#/settings">
        检查运行环境
      </a>
    </div>
  );
}
