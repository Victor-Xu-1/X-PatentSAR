import { useState } from 'react';
import { ImageOff } from 'lucide-react';
import { safeAssetUrl } from '../api';
export function AssetImage({
  url,
  alt,
  className = '',
  onLoad,
}: {
  url: string | null;
  alt: string;
  className?: string;
  onLoad?: () => void;
}) {
  const safe = safeAssetUrl(url);
  const [failed, setFailed] = useState<string | null>(null);
  if (!safe || failed === safe)
    return (
      <span className={`image-unavailable ${className}`} aria-label={`${alt}不可用`}>
        <ImageOff size={20} />
        <span>裁图不可用</span>
      </span>
    );
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
