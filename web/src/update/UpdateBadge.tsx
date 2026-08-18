type UpdateBadgeProps = {
  version: string;
  hasNotice: boolean;
  onClick: () => void;
};

export function UpdateBadge({ version, hasNotice, onClick }: UpdateBadgeProps) {
  return (
    <button
      type="button"
      className={`version-badge${hasNotice ? " version-badge-notice" : ""}`}
      onClick={hasNotice ? onClick : undefined}
      disabled={!hasNotice}
      aria-label={hasNotice ? `当前版本 V${version}，有新版本可更新` : `当前版本 V${version}`}
    >
      <span>V{version}</span>
      {hasNotice ? <span className="version-badge-dot" aria-hidden="true" /> : null}
    </button>
  );
}
