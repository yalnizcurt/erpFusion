import React from 'react';
export default function Footer({ identity }) {
  return <footer className="app-footer-bar footer"><span><span className="status-dot green-dot" />{identity ? 'Authenticated workspace' : 'Sign-in required'}<span className="footer-separator">/</span>HighStudio</span><span className="footer-note">© 2026 HighRadius</span></footer>;
}
