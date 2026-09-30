import React from 'react';

export default function HighRadiusLogo({ height = 26 }) {
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center' }}>
      <img
        src="/highradius-logo.svg"
        alt="HighRadius"
        style={{ height: `${height}px`, width: 'auto', display: 'block' }}
      />
    </div>
  );
}
