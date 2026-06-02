import { Download, Home, Pause, Play, RefreshCw, RotateCcw, Square, StepForward, Trash2, Wand2 } from "lucide-react";
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
        <button className="home-button" title="回到主页" disabled={busy} onClick={onNewWorld}>
          <Home size={16} /><span>主页</span>
        </button>
        <button title="继续" disabled={busy || world.status === "running"} onClick={onStart}><Play size={16} /></button>
        <button title="暂停" disabled={busy || world.status !== "running"} onClick={onPause}><Pause size={16} /></button>
        <button title="单步" disabled={busy} onClick={onStep}><StepForward size={16} /></button>
        <button title="解说" disabled={busy} onClick={onSummarize}><Wand2 size={16} /></button>
        <button title="刷新" disabled={busy} onClick={onRefresh}><RefreshCw size={16} /></button>
        <button title="结束" disabled={busy || world.status === "ended"} onClick={onEnd}><Square size={16} /></button>
        <button className="danger-icon-button" title="删除当前存档" disabled={busy} onClick={onDeleteWorld}><Trash2 size={16} /></button>
        <a title="导出当前人员预设" className="icon-link export-action" href={presetExportUrl}>
          <Download size={16} /><span>预设</span>
        </a>
        <a title="导出世界归档" className={`icon-link export-action ${world.status !== "ended" ? "disabled" : ""}`} href={world.status === "ended" ? exportUrl : undefined}>
          <Download size={16} /><span>归档</span>
        </a>
        {world.status === "ended" && (
          <button className="new-world-button" title="回到配置页" disabled={busy} onClick={onNewWorld}>
            <RotateCcw size={16} /><span>重新配置</span>
          </button>
        )}
      </div>
    </>
  );
}
