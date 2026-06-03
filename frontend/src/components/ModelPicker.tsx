import { useMemo, useState } from "react";

type ModelPickerProps = {
  value: string;
  models: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
  emptyLabel?: string;
  manualPlaceholder?: string;
  searchPlaceholder?: string;
  className?: string;
  maxVisible?: number;
};

function uniqueModels(models: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of models) {
    const model = String(raw ?? "").trim();
    if (!model || seen.has(model)) continue;
    seen.add(model);
    result.push(model);
  }
  return result;
}

export function ModelPicker({
  value,
  models,
  onChange,
  disabled = false,
  emptyLabel = "选择模型",
  manualPlaceholder = "手动输入模型名",
  searchPlaceholder = "搜索模型名",
  className = "",
  maxVisible = 250
}: ModelPickerProps) {
  const [query, setQuery] = useState("");
  const normalizedModels = useMemo(() => uniqueModels(models), [models]);
  const queryText = query.trim().toLowerCase();
  const filteredModels = useMemo(() => {
    const matched = queryText
      ? normalizedModels.filter((model) => model.toLowerCase().includes(queryText))
      : normalizedModels;
    return matched.slice(0, maxVisible);
  }, [maxVisible, normalizedModels, queryText]);
  const currentValue = value.trim();
  const shouldKeepCurrent = Boolean(currentValue) && !filteredModels.includes(currentValue);
  const optionModels = shouldKeepCurrent ? [currentValue, ...filteredModels] : filteredModels;

  if (!normalizedModels.length) {
    return (
      <input
        className={className}
        disabled={disabled}
        value={value}
        placeholder={manualPlaceholder}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }

  return (
    <div className={`model-picker ${className}`.trim()}>
      <input
        className="model-picker-search"
        disabled={disabled}
        value={query}
        placeholder={searchPlaceholder}
        onChange={(event) => setQuery(event.target.value)}
      />
      <select disabled={disabled} value={value} title={value || emptyLabel} onChange={(event) => onChange(event.target.value)}>
        <option value="">{emptyLabel}</option>
        {optionModels.map((model) => (
          <option key={model} value={model} title={model}>
            {shouldKeepCurrent && model === currentValue ? `当前: ${model}` : model}
          </option>
        ))}
      </select>
      <small>
        {filteredModels.length < normalizedModels.length ? `显示 ${filteredModels.length} / ${normalizedModels.length}` : `${normalizedModels.length} 个模型`}
      </small>
    </div>
  );
}
