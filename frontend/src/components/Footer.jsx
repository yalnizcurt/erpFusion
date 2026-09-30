import React from 'react';

export default function Footer() {
  return (
    <footer className="app-footer-bar" style={{
      textAlign: 'center',
      padding: '16px 20px',
      fontSize: '11px',
      color: '#64748b',
      borderTop: '1px solid #e2e8f0',
      background: '#ffffff',
      marginTop: 'auto',
    }}>
      <a
        href="https://www.highradius.com/privacy-policy/"
        target="_blank"
        rel="noreferrer"
        style={{ color: 'var(--hr-blue-primary)', textDecoration: 'none', fontWeight: '600' }}
      >
        Privacy policy
      </a>
      <span style={{ margin: '0 6px', color: '#cbd5e1' }}>|</span>
      <span>© 2026 HighRadius Corporation. All rights reserved.</span>
      <span style={{ margin: '0 6px', color: '#cbd5e1' }}>|</span>
      <span>Version: 26.2.0</span>
    </footer>
  );
}
