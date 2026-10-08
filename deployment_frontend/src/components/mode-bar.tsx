import { NavLink } from "react-router";

function ExploreIcon({ active }: { active: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
      <circle cx="11" cy="11" r="8.5" fill={active ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5" />
      <ellipse cx="11" cy="11" rx="3.6" ry="8.5" fill="none" stroke={active ? "var(--knockout)" : "currentColor"} strokeWidth="1.4" />
      <path d="M2.5 11h17" stroke={active ? "var(--knockout)" : "currentColor"} strokeWidth="1.4" />
    </svg>
  );
}

function WatchIcon({ active }: { active: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
      <rect x="3" y="4.5" width="16" height="13" rx="2" fill={active ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5" />
      <path d="M9.5 8.2v5.6l4.6-2.8Z" fill={active ? "var(--knockout)" : "currentColor"} />
    </svg>
  );
}

export function ModeBar() {
  return (
    <nav className="mode-bar" aria-label="Viewing mode">
      <NavLink to="/" end className="mode">
        {({ isActive }) => <><ExploreIcon active={isActive} />Explore</>}
      </NavLink>
      <NavLink to="/watch" className="mode">
        {({ isActive }) => <><WatchIcon active={isActive} />Watch</>}
      </NavLink>
    </nav>
  );
}
