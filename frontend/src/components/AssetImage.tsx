import { useState } from 'react';
import { ImageOff } from 'lucide-react';
import { safeAssetUrl } from '../api';
export function AssetImage({
  url,
  alt,
  className = '',
  onLoad,
  unavailableLabel = '未提供结构裁图',
}: {
  url: string | null;
  alt: string;
  className?: string;
  onLoad?: () => void;
  unavailableLabel?: string;
}) {
  const safe = safeAssetUrl(url);
  const [failed, setFailed] = useState<string | null>(null);
  if (!safe || failed === safe) {
    const message = !url ? unavailableLabel : !safe ? '裁图地址无效' : '裁图加载失败';
    return (
      <span className={`image-unavailable ${className}`} aria-label={`${alt}：${message}`}>
        <ImageOff size={20} />
        <span>{message}</span>
      </span>
    );
  }
  return (
    <img
      className={className}
      src={safe}
      alt={alt}
      loading="lazy"
      onLoad={onLoad}
      onError={() => setFailed(safe)}
    />
  );
}
