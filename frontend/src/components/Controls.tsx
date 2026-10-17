import type { ReactNode } from "react";
import { Archive, Download, Home, ImageIcon, ImagePlus, Pause, Play, RefreshCw, RotateCcw, Square, StepForward, Trash2, Wand2 } from "lucide-react";
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
  onDeleteWorld,
  monitor
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
  monitor?: ReactNode;
}) {
  const statusLabel =
    world.status === "running" ? "运行中" : world.status === "paused" ? "已暂停" : world.status === "ended" ? "已结束" : world.status;
  return (
    <>
      <div className="world-title">
        <button className="home-button" title="回到主页" aria-label="回到主页" onClick={onNewWorld}>
          <Home size={15} />
        </button>
        <div className="world-title-text">
          <strong title={world.name}>{world.name}</strong>
          <span className="world-clock">{world.world_time_label}</span>
        </div>
        {!monitor && <span className={`status-pill ${world.status}`} title={world.status}>{statusLabel}</span>}
        {monitor}
      </div>
      <div className="control-group">
        <div className="control-segment" role="group" aria-label="运行">
          <button title="继续" aria-label="继续" disabled={busy || world.status === "running"} onClick={onStart}><Play size={15} /></button>
          <button title="暂停" aria-label="暂停" disabled={busy || world.status !== "running"} onClick={onPause}><Pause size={15} /></button>
          <button title="单步" aria-label="单步" disabled={busy || world.status === "running"} onClick={onStep}><StepForward size={15} /></button>
        </div>

        <div className="control-segment" role="group" aria-label="生成">
          <button title="解说" aria-label="解说" disabled={busy} onClick={onSummarize}><Wand2 size={15} /></button>
          <button title="生图" aria-label="生图" disabled={busy} onClick={onGenerateImage}><ImageIcon size={15} /></button>
          <button title="手动提示词生图" aria-label="手动提示词生图" disabled={busy} onClick={onGenerateImagePrompt}><ImagePlus size={15} /></button>
          <button title="刷新" aria-label="刷新" disabled={busy} onClick={onRefresh}><RefreshCw size={15} /></button>
        </div>

        <div className="control-segment" role="group" aria-label="导出">
          <a className="icon-link" href={presetExportUrl} title="导出预设" aria-label="导出预设">
            <Download size={15} />
          </a>
          <a className={`icon-link ${world.status !== "ended" ? "disabled" : ""}`} href={world.status === "ended" ? exportUrl : undefined} title="导出归档（结束后可用）" aria-label="导出归档">
            <Archive size={15} />
          </a>
        </div>

        <div className="control-segment" role="group" aria-label="存档">
          {world.status === "ended" && (
            <button title="重新配置" aria-label="重新配置" onClick={onNewWorld}><RotateCcw size={15} /></button>
          )}
          <button title="结束模拟" aria-label="结束模拟" disabled={busy || world.status === "ended"} onClick={onEnd}><Square size={14} /></button>
          <button className="danger-icon-button" title="删除存档" aria-label="删除存档" disabled={busy} onClick={onDeleteWorld}><Trash2 size={15} /></button>
        </div>
      </div>
    </>
  );
}
