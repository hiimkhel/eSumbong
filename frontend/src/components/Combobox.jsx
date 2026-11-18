import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

// Text field with a filtered, styled option list: type to narrow it down, or
// open it with the arrow and click. Arrow keys move, Enter picks, Escape closes.
// options: [{ value, label, hint?, text? }]. Picking puts `text` (default: label)
// in the field; hint is a second line. onChange(text) gets what is typed or picked.
export default function Combobox({ value, onChange, options, placeholder, icon: Icon, invalid, required, className = "", id }) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const query = value.trim().toLowerCase();
  const textOf = (o) => o.text ?? o.label;
  const keys = (o) => [o.label, textOf(o)].map((k) => k.toLowerCase());
  const exact = options.some((o) => keys(o).includes(query));
  // Options that start with the text first, then ones that contain it.
  const starts = (o) => keys(o).some((k) => k.startsWith(query));
  const matches = !query || exact
    ? options
    : [...options.filter(starts), ...options.filter((o) => !starts(o) && keys(o).some((k) => k.includes(query)))];

  function pick(option) {
    onChange(textOf(option));
    setOpen(false);
  }

  function onKeyDown(e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return setOpen(true);
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (i + step + matches.length) % Math.max(matches.length, 1));
    } else if (e.key === "Enter" && open && matches[active]) {
      e.preventDefault(); // pick, don't submit the form
      pick(matches[active]);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      setOpen(false);
    }
  }

  const optionId = (i) => `${listId}-${i}`;

  return (
    <span className="combo">
      <span className={Icon ? "input-icon" : undefined}>
        {Icon && <Icon size={17} />}
        <input id={id} className={`input combo-input ${className}`.trim()} role="combobox" autoComplete="off" required={required}
          aria-expanded={open} aria-controls={listId} aria-autocomplete="list" aria-invalid={invalid || undefined}
          aria-activedescendant={open && matches[active] ? optionId(active) : undefined}
          placeholder={placeholder} value={value}
          onChange={(e) => { onChange(e.target.value); setActive(0); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown} />
        <button type="button" className="combo-toggle" tabIndex={-1} aria-label="Show options"
          onMouseDown={(e) => { e.preventDefault(); setOpen((o) => !o); }}>
          <ChevronDown size={18} />
        </button>
      </span>
      {open && (
        <ul className="combo-list" id={listId} role="listbox">
          {matches.length === 0 && <li className="combo-empty">No match</li>}
          {matches.map((o, i) => (
            <li key={o.value} id={optionId(i)} role="option" aria-selected={i === active}
              className="combo-option"
              onMouseDown={(e) => { e.preventDefault(); pick(o); }}
              onMouseEnter={() => setActive(i)}>
              {o.label}
              {o.hint && <small className="combo-hint">{o.hint}</small>}
            </li>
          ))}
        </ul>
      )}
    </span>
  );
}
