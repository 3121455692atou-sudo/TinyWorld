import { useRef, useState } from "react";

type WorkflowJsonInputProps = {
  value: string;
  label: string;
  placeholder?: string;
  className?: string;
  onChange: (value: string) => void;
};

export function WorkflowJsonInput({ value, label, placeholder, className = "", onChange }: WorkflowJsonInputProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");

  const applyFile = async (file: File | undefined) => {
    if (!file) return;
    const text = await file.text();
    try {
      JSON.parse(text);
    } catch {
      setError("不是有效的 JSON 文件");
      return;
    }
    setError("");
    onChange(text);
  };

  return (
    <div
      className={`workflow-json-input ${dragging ? "dragging" : ""} ${className}`.trim()}
      onDragEnter={(event) => {
        event.preventDefault();
        event.stopPropagation();
        setDragging(true);
      }}
      onDragOver={(event) => {
        event.preventDefault();
        event.stopPropagation();
      }}
      onDragLeave={(event) => {
        event.preventDefault();
        event.stopPropagation();
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        event.stopPropagation();
        setDragging(false);
        void applyFile(event.dataTransfer.files?.[0]);
      }}
    >
      <div className="workflow-json-heading">
        <span>{label}</span>
        <button type="button" onClick={() => inputRef.current?.click()}>导入 JSON</button>
      </div>
      <textarea value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
      <div className="workflow-json-help">
        <span>把 ComfyUI 导出的 API JSON 拖到这里，或点“导入 JSON”。</span>
        {error && <strong>{error}</strong>}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={(event) => {
          void applyFile(event.target.files?.[0]);
          event.currentTarget.value = "";
        }}
      />
    </div>
  );
}
