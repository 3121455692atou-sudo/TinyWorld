import { Download, Home, ImageIcon, ImagePlus, MoreHorizontal, Pause, Play, RefreshCw, RotateCcw, Square, StepForward, Trash2, Wand2 } from "lucide-react";
import { useRef, useState } from "react";
import type { World } from "../api/types";

export function Controls({
  world,
  busy,
  exportUrl,
  presetExportUrl,
  onStart,
  onPause,
  onStep,
  onEnd,
  onSummarize,
  onGenerateImage,
  onGenerateImagePrompt,
  onRefresh,
  onNewWorld,
  onDeleteWorld
}: {
  world: World;
  busy: boolean;
  exportUrl: string;
  presetExportUrl: string;
  onStart: () => void;
  onPause: () => void;
  onStep: () => void;
  onEnd: () => void;
  onSummarize: () => void;
  onGenerateImage: () => void;
  onGenerateImagePrompt: () => void;
  onRefresh: () => void;
  onNewWorld: () => void;
  onDeleteWorld: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  return (
    <>
      <div className="world-title">
        <strong>{world.name}</strong>
        <span>{world.world_time_label}</span>
        <span className={`status-pill ${world.status}`}>{world.status}</span>
      </div>
      <div className="control-group">
        <button className="home-button" title="回到主页" onClick={onNewWorld}>
          <Home size={16} /><span>主页</span>
        </button>

        <span className="control-divider" />

        <button title="继续" disabled={busy || world.status === "running"} onClick={onStart}><Play size={16} /></button>
        <button title="暂停" disabled={busy || world.status !== "running"} onClick={onPause}><Pause size={16} /></button>
        <button title="单步" disabled={busy || world.status === "running"} onClick={onStep}><StepForward size={16} /></button>

        <span className="control-divider" />

        <button title="解说" disabled={busy} onClick={onSummarize}><Wand2 size={16} /></button>
        <button title="生图" disabled={busy} onClick={onGenerateImage}><ImageIcon size={16} /></button>
        <button title="刷新" disabled={busy} onClick={onRefresh}><RefreshCw size={16} /></button>

        <span className="control-divider" />

        <div className="control-more" ref={menuRef}>
          <button
            className={`control-more-trigger ${menuOpen ? "active" : ""}`}
            title="更多操作"
            onClick={() => setMenuOpen((v) => !v)}
          >
            <MoreHorizontal size={16} />
          </button>
          {menuOpen && (
            <>
              <div className="control-more-scrim" onClick={() => setMenuOpen(false)} />
              <div className="control-more-menu">
                <button disabled={busy} onClick={() => { onGenerateImagePrompt(); setMenuOpen(false); }}>
                  <ImagePlus size={14} /><span>手动提示词生图</span>
                </button>
                <button disabled={busy || world.status === "ended"} onClick={() => { onEnd(); setMenuOpen(false); }}>
                  <Square size={14} /><span>结束模拟</span>
                </button>
                <a className="control-more-link" href={presetExportUrl} onClick={() => setMenuOpen(false)}>
                  <Download size={14} /><span>导出预设</span>
                </a>
                <a className={`control-more-link ${world.status !== "ended" ? "disabled" : ""}`} href={world.status === "ended" ? exportUrl : undefined} onClick={() => setMenuOpen(false)}>
                  <Download size={14} /><span>导出归档</span>
                </a>
                <span className="control-more-sep" />
                <button className="danger" disabled={busy} onClick={() => { onDeleteWorld(); setMenuOpen(false); }}>
                  <Trash2 size={14} /><span>删除存档</span>
                </button>
                {world.status === "ended" && (
                  <button onClick={() => { onNewWorld(); setMenuOpen(false); }}>
                    <RotateCcw size={14} /><span>重新配置</span>
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
