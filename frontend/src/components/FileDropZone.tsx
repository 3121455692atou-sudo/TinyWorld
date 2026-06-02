import { useRef, useState, type ReactNode } from "react";

type FileDropZoneProps = {
  accept?: string;
  disabled?: boolean;
  className?: string;
  buttonClassName?: string;
  hint?: string;
  children: ReactNode;
  onFile: (file: File) => void | Promise<void>;
};

export function FileDropZone({ accept, disabled = false, className = "", buttonClassName = "", hint, children, onFile }: FileDropZoneProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);

  const applyFile = (file: File | undefined) => {
    if (!file || disabled) return;
    void onFile(file);
  };

  return (
    <div
      className={`file-drop-zone ${dragging ? "dragging" : ""} ${disabled ? "disabled" : ""} ${className}`.trim()}
      onDragEnter={(event) => {
        event.preventDefault();
        event.stopPropagation();
        if (!disabled) setDragging(true);
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
        applyFile(event.dataTransfer.files?.[0]);
      }}
    >
      <button type="button" className={buttonClassName || undefined} disabled={disabled} onClick={() => inputRef.current?.click()}>
        {children}
      </button>
      {hint && <span className="file-drop-hint">{hint}</span>}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        hidden
        disabled={disabled}
        onChange={(event) => {
          applyFile(event.target.files?.[0]);
          event.currentTarget.value = "";
        }}
      />
    </div>
  );
}
