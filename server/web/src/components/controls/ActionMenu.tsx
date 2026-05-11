interface ActionMenuItem {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
}

export function ActionMenu({ items }: { items: ActionMenuItem[] }) {
  return (
    <div className="toolbar" role="menu">
      {items.map((item) => (
        <button
          className="button"
          disabled={item.disabled}
          key={item.label}
          onClick={item.onSelect}
          type="button"
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
