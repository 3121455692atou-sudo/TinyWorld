import { Download, Home, ImageIcon, ImagePlus, Pause, Play, RefreshCw, RotateCcw, Square, StepForward, Trash2, Wand2 } from "lucide-react";
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

        <button title="手动提示词生图" disabled={busy} onClick={onGenerateImagePrompt}><ImagePlus size={16} /></button>
        <button title="结束模拟" disabled={busy || world.status === "ended"} onClick={onEnd}><Square size={16} /></button>
        <a className="icon-link" href={presetExportUrl} title="导出预设">
          <Download size={16} />
        </a>
        <a className={`icon-link ${world.status !== "ended" ? "disabled" : ""}`} href={world.status === "ended" ? exportUrl : undefined} title="导出归档">
          <Download size={16} />
        </a>
        <button className="danger-icon-button" title="删除存档" disabled={busy} onClick={onDeleteWorld}><Trash2 size={16} /></button>
        {world.status === "ended" && (
          <button title="重新配置" onClick={onNewWorld}><RotateCcw size={16} /></button>
        )}
      </div>
    </>
  );
}
