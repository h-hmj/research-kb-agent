import type { DocumentSummary } from "../api/types";

export function DocumentFilter({
  documents,
  selected,
  onChange,
  label = "限制文档范围（可选）",
}: {
  documents: DocumentSummary[];
  selected: string[];
  onChange: (ids: string[]) => void;
  label?: string;
}) {
  const indexed = documents.filter((item) => item.index_status === "indexed");
  if (indexed.length === 0) {
    return (
      <p className="hint">当前没有已索引文档，将检索全部已索引内容。</p>
    );
  }
  return (
    <label className="field">
      <span>{label}</span>
      <select
        multiple
        size={Math.min(4, Math.max(2, indexed.length))}
        value={selected}
        onChange={(event) => {
          const ids = Array.from(
            event.currentTarget.selectedOptions,
            (option) => option.value,
          );
          onChange(ids);
        }}
      >
        {indexed.map((document) => (
          <option key={document.id} value={document.id}>
            {document.original_filename}
          </option>
        ))}
      </select>
      <small className="hint">按住 Ctrl / Command 可多选。</small>
    </label>
  );
}
