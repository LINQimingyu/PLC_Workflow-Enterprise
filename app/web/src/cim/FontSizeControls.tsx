import { useEffect, useState } from "react";

const sizes = [90, 100, 110, 120, 130];
const storageKey = "factory-font-percent";
export function useFontSize() {
  const [percent, setPercent] = useState(() => {
    try { const saved = Number(localStorage.getItem(storageKey)); return sizes.includes(saved) ? saved : 100; }
    catch { return 100; }
  });
  useEffect(() => {
    try { localStorage.setItem(storageKey, String(percent)); } catch { /* The control still works without persistent storage. */ }
  }, [percent]);
  return [percent, setPercent] as const;
}

export default function FontSizeControls({ percent, onChange }: { percent: number; onChange: (value: number) => void }) {
  const index = sizes.indexOf(percent);
  return <div className="fc-font-controls" role="group" aria-label="字号调节">
    <span>字号</span>
    <button type="button" className="secondary" aria-label="缩小字号" disabled={index === 0} onClick={() => onChange(sizes[index - 1])}>A−</button>
    <button type="button" className="secondary fc-font-reset" aria-label="恢复默认字号" onClick={() => onChange(100)}><output aria-label="当前字号" aria-live="polite">{percent}%</output></button>
    <button type="button" className="secondary" aria-label="放大字号" disabled={index === sizes.length - 1} onClick={() => onChange(sizes[index + 1])}>A＋</button>
  </div>;
}
