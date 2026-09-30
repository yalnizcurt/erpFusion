import React from 'react';
import HighRadiusLogo from '../assets/HighRadiusLogo';

export default function Header() {
  return (
    <header className="app-header-bar" style={{
      height: '52px',
      background: '#ffffff',
      borderBottom: '1px solid var(--border-light)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 24px',
      position: 'relative',
      zIndex: 5,
    }}>
      {/* Product Title & Brand */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {/* Orange ERP Icon */}
        <div style={{
          width: '24px',
          height: '24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fc7500',
        }}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="#fc7500">
            <path d="M12 3L2 12h3v8h6v-6h2v6h6v-8h3L12 3z"/>
          </svg>
        </div>

        <h1 style={{
          fontSize: '18px',
          fontWeight: '700',
          color: '#1e293b',
          letterSpacing: '-0.02em',
          margin: 0,
        }}>
          erp<span style={{ color: 'var(--hr-orange)' }}>Fusion</span>
        </h1>

        <span style={{
          fontSize: '11px',
          padding: '2px 8px',
          background: 'var(--hr-orange-subtle)',
          color: 'var(--hr-orange)',
          border: '1px solid var(--hr-orange-border)',
          borderRadius: '4px',
          fontWeight: '600',
          marginLeft: '4px'
        }}>
          AI Integration Engineering Agent
        </span>
      </div>

      {/* Right: User Avatar & HighRadius Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        {/* User Initials Badge */}
        <div
          title="Lead Engineer (Human Reviewer)"
          style={{
            width: '32px',
            height: '32px',
            borderRadius: '50%',
            background: '#047857',
            color: '#ffffff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '13px',
            fontWeight: '600',
            letterSpacing: '0.02em',
            cursor: 'pointer',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
          }}
        >
          LE
        </div>

        {/* HighRadius Official Brand Logo */}
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <HighRadiusLogo height={24} />
        </div>
      </div>
    </header>
  );
}
