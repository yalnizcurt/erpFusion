import React, { useEffect, useState, useSyncExternalStore } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import NewProjectModal from './components/NewProjectModal';
import Footer from './components/Footer';
import ERPAdmin from './components/ERPAdmin';
import ClientWorkspace from './components/ClientWorkspace';
import ProjectDirectory from './components/ProjectDirectory';
import ProjectStudio from './components/ProjectStudio';
import { requestJson, subscribeAuthenticationChanges } from './api';
import { useApiResource } from './hooks/useApiResource';
import { beginSignIn, getOidcState, initializeOidc, signOut, subscribeOidcState } from './auth/oidc';

export default function App() {
  const auth = useSyncExternalStore(subscribeOidcState, getOidcState);
  useEffect(() => { void initializeOidc(); }, []);
  const [authenticationRevision, setAuthenticationRevision] = useState(0);
  useEffect(() => subscribeAuthenticationChanges(() => setAuthenticationRevision((value) => value + 1)), []);
  const session = useApiResource(!auth.configured || auth.status === 'signed_in' ? '/api/identity/me' : null, authenticationRevision);
  const logout = auth.configured && auth.status === 'signed_in' ? signOut : undefined;
  const login = auth.configured && auth.status !== 'initializing' && auth.status !== 'signed_in' ? () => { void beginSignIn(); } : undefined;
  if (!session.data) {
    return <div className="app-shell"><Sidebar /><div className="app-main-column"><Header onSignIn={login} onSignOut={logout} />
      <main className="app-content-scroll" style={{ padding: 24 }}>
        {session.loading || auth.status === 'initializing' ? <p role="status">Verifying your access…</p> : <div role="alert"><h2>{auth.status === 'signed_in' ? 'Portal access unavailable' : 'Sign-in required'}</h2><p>{auth.error || session.error || (auth.configured ? 'Sign in with your organization’s account to access the portal.' : 'No authenticated identity is available.')}</p><p>{auth.status === 'signed_in' ? 'Retry access when the service is available. If access is still denied, ask an administrator to provision your portal account and client access.' : auth.configured ? 'After reloading this page, sign in again to restore your session.' : 'Use your organization’s configured sign-in connection to access the portal.'}</p>{auth.status === 'signed_in' && <button type="button" className="btn btn-secondary" onClick={session.reload}>Retry access</button>}</div>}
      </main><Footer /></div></div>;
  }
  return <EngineeringApp key={`${authenticationRevision}:${session.data.user_id}`} identity={session.data} onSignOut={logout} />;
}

function readRoute() {
  const match = window.location.pathname.match(/^\/projects\/([^/]+)\/studio\/?$/);
  if (match) return { page: 'studio', projectId: decodeURIComponent(match[1]) };
  return { page: window.location.pathname === '/clients' ? 'clients' : window.location.pathname === '/erp-profiles' ? 'erp-admin' : 'home', projectId: null };
}

function EngineeringApp({ identity, onSignOut }) {
  const [route, setRoute] = useState(readRoute);
  const [resumeId, setResumeId] = useState(route.projectId);
  const [requirementDirty, setRequirementDirty] = useState(false);
  const [directoryState, setDirectoryState] = useState({ filters: { search: '', erp_profile_id: '', project_type: '', request_status: '' }, offset: 0, sort: 'last_activity:desc' });
  useEffect(() => {
    const update = () => {
      const next = readRoute();
      if (route.page === 'studio' && requirementDirty && (next.page !== 'studio' || next.projectId !== route.projectId)) {
        if (!window.confirm('Discard unsaved requirement edits? Save the requirement revision to keep them.')) {
          window.history.go(1);
          return;
        }
        setRequirementDirty(false);
      }
      setRoute(next); if (next.projectId) setResumeId(next.projectId);
    };
    window.addEventListener('popstate', update);
    return () => window.removeEventListener('popstate', update);
  }, [requirementDirty, route]);
  const navigate = (path) => {
    if (requirementDirty && route.page === 'studio' && path !== window.location.pathname) {
      if (!window.confirm('Discard unsaved requirement edits? Save the requirement revision to keep them.')) return;
      setRequirementDirty(false);
    }
    window.history.pushState({}, '', path);
    const next = readRoute(); setRoute(next); if (next.projectId) setResumeId(next.projectId);
  };
  const profileResource = useApiResource('/api/erp-profiles');
  const [showNewProjectModal, setShowNewProjectModal] = useState(false);
  const canCreate = identity.capabilities.manage_clients || identity.clients.some((client) => client.permissions.create_request);
  const createProject = async (body) => {
    const created = await requestJson('/api/projects', { method: 'POST', body: JSON.stringify(body) });
    navigate(`/projects/${encodeURIComponent(created.id)}/studio`);
  };
  return <div className="app-shell">
    <Sidebar activeNav={route.page} identity={identity} canConfigureERP={identity.capabilities.configure_erp || identity.capabilities.publish_erp} onSelectNav={(page) => {
      if (page === 'erp-admin' && !identity.capabilities.configure_erp && !identity.capabilities.publish_erp) return;
      navigate(page === 'studio' && resumeId ? `/projects/${encodeURIComponent(resumeId)}/studio` : page === 'studio' ? '/studio' : page === 'clients' ? '/clients' : page === 'erp-admin' ? '/erp-profiles' : '/');
    }} />
    <div className="app-main-column shell-column">
      <Header identity={identity} onHome={() => navigate('/')} onSignOut={onSignOut} pageTitle={route.page === 'studio' ? 'Engineering Studio' : route.page === 'clients' ? 'Clients' : route.page === 'erp-admin' ? 'ERP Profiles' : 'Projects'} />
      <main className="app-content-scroll main" id="main">
        {route.page === 'erp-admin' ? <ERPAdmin identity={identity} onBack={() => navigate('/')} onRegistryChanged={profileResource.reload} />
          : route.page === 'clients' ? <ClientWorkspace erpProfiles={profileResource.data || []} identity={identity} />
          : route.projectId ? <ProjectStudio erpProfiles={profileResource.data || []} key={route.projectId} projectId={route.projectId} identity={identity} onHome={() => navigate('/')} onConnections={() => navigate('/clients')} onRequirementDirtyChange={setRequirementDirty} />
          : <ProjectDirectory directoryState={directoryState} onDirectoryChange={setDirectoryState} profiles={profileResource.data || []} profileError={profileResource.error} selecting={window.location.pathname === '/studio'} onOpen={(id) => navigate(`/projects/${encodeURIComponent(id)}/studio`)} onCreate={canCreate ? () => setShowNewProjectModal(true) : undefined} />}
      </main>
      <Footer identity={identity} />
    </div>
    {showNewProjectModal && <NewProjectModal identity={identity} erpProfiles={profileResource.data || []} onClose={() => setShowNewProjectModal(false)} onCreateProject={createProject} />}
  </div>;
}
