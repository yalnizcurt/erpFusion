import React from 'react';

export default function Header({ identity, onSignIn, onSignOut, onHome, pageTitle = 'Projects' }) {
  return <header className="app-header-bar header">
    <a className="wordmark" href="/" onClick={(event) => { if (onHome) { event.preventDefault(); onHome(); } }}>High<span>Studio</span></a><span className="header-divider" /><span className="header-context">{pageTitle}</span>
    <div className="header-right">
      {identity?.is_fixture && <span className="prototype-chip">Development fixture</span>}
      {onSignIn && <button className="btn secondary" onClick={onSignIn}>Sign in</button>}
      {onSignOut && <button className="btn ghost" onClick={onSignOut}>Sign out</button>}
      <div className="user-avatar" title={identity ? `Signed in as ${identity.user_id}` : 'Sign-in required'}>{identity ? identity.user_id.slice(0, 2).toUpperCase() : '—'}</div>
      <img className="highradius" src="/highradius-logo.svg" alt="HighRadius" />
    </div>
  </header>;
}
