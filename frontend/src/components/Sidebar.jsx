import React from 'react';
import { Home, LayoutDashboard, Zap, Settings2 } from 'lucide-react';

export default function Sidebar({ activeNav = 'home', onSelectNav }) {
  const navItems = [
    { id: 'home', label: 'Home', icon: Home },
    { id: 'projects', label: 'Traceability', icon: LayoutDashboard },
    { id: 'pipelines', label: 'Pipeline', icon: Zap },
    { id: 'erp-admin', label: 'ERP Profiles', icon: Settings2 },
  ];

  return (
    <aside
      className="app-sidebar"
      style={{
        width: '54px',
        height: '100%',
        minHeight: '100vh',
        background: '#0096e6',
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        paddingTop: '16px',
        gap: '12px',
        boxSizing: 'border-box',
      }}
    >
      {navItems.map((item) => {
        const Icon = item.icon;
        const isActive = activeNav === item.id;

        return (
          <button
            key={item.id}
            id={`nav-${item.id}`}
            title={item.label}
            aria-label={item.label}
            onClick={() => onSelectNav && onSelectNav(item.id)}
            style={{
              width: '42px',
              height: '42px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              background: isActive ? '#ffffff' : 'transparent',
              color: isActive ? '#0096e6' : 'rgba(255, 255, 255, 0.85)',
              boxShadow: isActive ? '0 2px 6px rgba(0, 0, 0, 0.12)' : 'none',
              padding: 0,
              outline: 'none',
            }}
          >
            <Icon size={20} />
          </button>
        );
      })}
    </aside>
  );
}
