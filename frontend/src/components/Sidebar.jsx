import React from 'react';
import { Building2, Home, Layers, Zap, Settings2 } from 'lucide-react';

export default function Sidebar({ activeNav = 'home', onSelectNav, canConfigureERP = false, identity }) {
  const items = [{ id: 'home', label: 'Home', icon: Home }, { id: 'studio', label: 'Studio', icon: Zap }, { id: 'clients', label: 'Clients', icon: Building2 }, { id: 'erp-admin', label: 'ERP Profiles', icon: Settings2 }];
  return <aside className="app-sidebar sidebar" aria-label="Main navigation">
    <button className="rail-brand" aria-label="HighStudio Home" onClick={() => onSelectNav?.('home')}><Layers className="icon" /></button>
    <nav>{items.filter((item) => item.id !== 'erp-admin' || canConfigureERP).map((item) => <button key={item.id} id={`nav-${item.id}`} title={item.label} aria-label={item.label} aria-current={activeNav === item.id ? 'page' : undefined} className={`rail-link ${activeNav === item.id ? 'active' : ''}`} onClick={() => onSelectNav?.(item.id)}><item.icon className="icon" /><span>{item.label}</span></button>)}</nav>
    <div className="rail-bottom"><div className="rail-avatar" title={identity?.user_id || 'Sign-in required'}>{identity ? identity.user_id.slice(0, 2).toUpperCase() : '—'}</div></div>
  </aside>;
}
