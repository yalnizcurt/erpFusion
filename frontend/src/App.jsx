import React, { useState, useEffect, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import FilterControlBar from './components/FilterControlBar';
import PipelineOverviewCard from './components/PipelineOverviewCard';
import BottomCards from './components/BottomCards';
import DiffViewer from './components/DiffViewer';
import TraceabilityCard from './components/TraceabilityCard';
import DeploymentPackageView from './components/DeploymentPackageView';
import NewProjectModal from './components/NewProjectModal';
import Footer from './components/Footer';
import ERPAdmin from './components/ERPAdmin';
import { apiUrl } from './api';

export default function App() {
  const [projects, setProjects] = useState([]);
  const [erpProfiles, setErpProfiles] = useState([]);
  const [activeProject, setActiveProject] = useState(null);
  const [artifacts, setArtifacts] = useState([]);
  const [workflowStages, setWorkflowStages] = useState([]);
  const [selectedStage, setSelectedStage] = useState('CONTEXT_ANALYSIS');
  const [versions, setVersions] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [validations, setValidations] = useState([]);

  const [activeNav, setActiveNav] = useState('home');
  const [activeTab, setActiveTab] = useState('pipeline');

  const [isGenerating, setIsGenerating] = useState(false);

  // Modals
  const [showNewProjectModal, setShowNewProjectModal] = useState(false);
  const [showDiffModal, setShowDiffModal] = useState(false);

  // API Calls (memoized)
  const loadProjects = useCallback(async () => {
    try {
      const res = await fetch(apiUrl('/api/projects'));
      if (res.ok) {
        const data = await res.json();
        setProjects(data.projects || []);
        if (data.projects && data.projects.length > 0) {
          setActiveProject((prev) => prev || data.projects[0]);
        }
      }
    } catch (e) {
      console.error('Failed to load projects', e);
    }
  }, []);

  const loadErpProfiles = useCallback(async () => {
    try {
      const res = await fetch(apiUrl('/api/erp-profiles'));
      if (res.ok) setErpProfiles(await res.json());
    } catch (e) {
      console.error('Failed to load ERP profiles', e);
    }
  }, []);

  const loadArtifacts = useCallback(async (projectId) => {
    try {
      const res = await fetch(apiUrl(`/api/projects/${projectId}/artifacts`));
      if (res.ok) {
        const arts = await res.json();
        setArtifacts(arts);
      }
    } catch (e) {
      console.error('Failed to load artifacts', e);
    }
  }, []);

  const loadWorkflow = useCallback(async (projectId) => {
    try {
      const res = await fetch(apiUrl(`/api/projects/${projectId}/workflow`));
      if (!res.ok) throw new Error(`Workflow request failed (${res.status})`);
      const data = await res.json();
      const nextStages = data.stages || [];
      setWorkflowStages(nextStages);
      const activeStage = nextStages.find((item) => item.stage === data.current_stage);
      setSelectedStage(activeStage?.stage || nextStages[0]?.stage || '');
    } catch (e) {
      setWorkflowStages([]);
      setSelectedStage('');
      console.error('Failed to load project workflow', e);
    }
  }, []);

  const loadVersions = useCallback(async (artifactId) => {
    try {
      const res = await fetch(apiUrl(`/api/artifacts/${artifactId}/versions`));
      if (res.ok) {
        const vList = await res.json();
        setVersions(vList);
        if (vList.length > 0) {
          setSelectedVersion(vList[0]);
        } else {
          setSelectedVersion(null);
        }
      }
    } catch (e) {
      console.error('Failed to load versions', e);
    }
  }, []);

  const loadValidations = useCallback(async (artifactId, versionNumber) => {
    try {
      const res = await fetch(apiUrl(`/api/artifacts/${artifactId}/versions/${versionNumber}/validations`));
      if (res.ok) {
        const valData = await res.json();
        setValidations(valData);
      }
    } catch (e) {
      console.error('Failed to load validations', e);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadProjects();
    loadErpProfiles();
  }, [loadProjects, loadErpProfiles]);

  // When active project changes, load its artifacts
  useEffect(() => {
    if (activeProject) {
      setArtifacts([]);
      setWorkflowStages([]);
      setSelectedStage('');
      setVersions([]);
      setSelectedVersion(null);
      setValidations([]);
      loadArtifacts(activeProject.id);
      loadWorkflow(activeProject.id);
    }
  }, [activeProject, loadArtifacts, loadWorkflow]);

  // When selected stage or artifacts change, load versions for the stage
  useEffect(() => {
    if (artifacts.length > 0 && selectedStage) {
      const art = artifacts.find((a) => a.artifact_type === selectedStage);
      if (art) {
        loadVersions(art.id);
      } else {
        setVersions([]);
        setSelectedVersion(null);
        setValidations([]);
      }
    }
  }, [selectedStage, artifacts, loadVersions]);

  // When selected version changes, load its validation checks
  useEffect(() => {
    if (selectedVersion) {
      const art = artifacts.find((a) => a.artifact_type === selectedStage);
      if (art) {
        loadValidations(art.id, selectedVersion.version_number);
      }
    } else {
      setValidations([]);
    }
  }, [selectedVersion, selectedStage, artifacts, loadValidations]);

  const handleCreateProject = async (projectData) => {
    const res = await fetch(apiUrl('/api/projects'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(projectData),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to create project');
    }
    const newProj = await res.json();
    await loadProjects();
    setActiveProject(newProj);
    setSelectedStage('CONTEXT_ANALYSIS');
  };

  const handleGenerate = async (stageType) => {
    if (!activeProject) return;
    setIsGenerating(true);
    try {
      const res = await fetch(apiUrl(`/api/projects/${activeProject.id}/generate`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage: stageType }),
      });

      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || 'Generation failed');
        return;
      }

      const newVersion = await res.json();
      await loadArtifacts(activeProject.id);
      await loadWorkflow(activeProject.id);
      setSelectedVersion(newVersion);
    } catch (e) {
      console.error('Generation error', e);
      alert('Generation error: ' + e.message);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleApprove = async (versionNumber, reviewer) => {
    const art = artifacts.find((a) => a.artifact_type === selectedStage);
    if (!art) return;

    try {
      const res = await fetch(apiUrl(`/api/reviews/artifacts/${art.id}/versions/${versionNumber}/review`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: 'APPROVED',
          reviewer: reviewer || 'Lead Architect',
          comments: 'Approved by lead integration engineer.',
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || 'Approval failed');
        return;
      }

      await loadArtifacts(activeProject.id);
      await loadWorkflow(activeProject.id);
      await loadVersions(art.id);
    } catch (e) {
      console.error('Approval failed', e);
    }
  };

  const handleRequestChanges = async (versionNumber, reviewer, comments) => {
    const art = artifacts.find((a) => a.artifact_type === selectedStage);
    if (!art) return;

    try {
      const res = await fetch(apiUrl(`/api/reviews/artifacts/${art.id}/versions/${versionNumber}/review`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: 'REQUEST_CHANGES',
          reviewer: reviewer || 'Lead Architect',
          comments: comments,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || 'Failed to request changes');
        return;
      }

      await loadArtifacts(activeProject.id);
      await loadWorkflow(activeProject.id);
      await loadVersions(art.id);
    } catch (e) {
      console.error('Request changes error', e);
    }
  };

  const handleReject = async (versionNumber, reviewer, comments) => {
    const art = artifacts.find((a) => a.artifact_type === selectedStage);
    if (!art) return;

    try {
      const res = await fetch(apiUrl(`/api/reviews/artifacts/${art.id}/versions/${versionNumber}/review`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: 'REJECTED',
          reviewer: reviewer || 'Lead Architect',
          comments: comments,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || 'Failed to reject version');
        return;
      }

      await loadArtifacts(activeProject.id);
      await loadWorkflow(activeProject.id);
      await loadVersions(art.id);
    } catch (e) {
      console.error('Reject error', e);
    }
  };

  const checkCanGenerate = (stageType) => {
    return workflowStages.find((item) => item.stage === stageType)?.can_generate || false;
  };

  const currentArtifact = artifacts.find((a) => a.artifact_type === selectedStage) || null;

  // Inline tabs — only 3
  const tabs = [
    { id: 'pipeline', label: 'Pipeline' },
    { id: 'traceability', label: 'Traceability' },
    { id: 'deployment', label: 'Deployment' },
  ];

  return (
    <div className="app-shell">
      {/* Left Sidebar */}
      <Sidebar activeNav={activeNav} onSelectNav={(nav) => {
        setActiveNav(nav);
        if (nav === 'home' || nav === 'pipelines') setActiveTab('pipeline');
        if (nav === 'projects') setActiveTab('traceability');
      }} />

      {/* Main Column */}
      <div className="app-main-column">
        {/* Top Header */}
        <Header />

        {activeNav !== 'erp-admin' && <>
        {/* Inline Tab Bar — 3 tabs */}
        <div className="app-tab-bar" style={{
          display: 'flex',
          alignItems: 'flex-end',
          padding: '0 24px',
          background: '#ffffff',
          borderBottom: '2px solid var(--hr-blue-primary)',
          height: '42px',
        }}>
          {tabs.map((t) => {
            const isActive = activeTab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => {
                  setActiveTab(t.id);
                  setActiveNav(t.id === 'traceability' ? 'projects' : 'pipelines');
                }}
                style={{
                  padding: '8px 18px',
                  fontSize: '13px',
                  fontWeight: isActive ? '600' : '500',
                  color: isActive ? '#1e293b' : '#64748b',
                  background: isActive ? '#ffffff' : 'transparent',
                  border: isActive ? '1px solid var(--hr-blue-primary)' : '1px solid transparent',
                  borderBottom: isActive ? '2px solid #ffffff' : '1px solid transparent',
                  marginBottom: isActive ? '-2px' : '0',
                  borderRadius: '6px 6px 0 0',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                  fontFamily: 'inherit',
                  outline: 'none',
                }}
              >
                {t.label}
              </button>
            );
          })}
        </div>

        {/* Simplified Filter Control Bar */}
        <FilterControlBar
          projects={projects}
          activeProject={activeProject}
          onSelectProject={(id) => {
            const p = projects.find((x) => x.id === id);
            if (p) setActiveProject(p);
          }}
          onNewProject={() => setShowNewProjectModal(true)}
          selectedStage={selectedStage}
          onGenerate={() => handleGenerate(selectedStage)}
          isGenerating={isGenerating}
          canGenerate={checkCanGenerate(selectedStage)}
        />
        </>}

        {/* Main Content Area */}
        <main className="app-content-scroll">
          {activeNav === 'erp-admin' ? (
            <ERPAdmin onBack={() => setActiveNav('home')} />
          ) : <>
          {activeTab === 'pipeline' && (
            <>
              {/* Top Section: 6-Stage Gate Architecture & Integration Health Card */}
              <PipelineOverviewCard
                artifacts={artifacts}
                stages={workflowStages}
                activeProject={activeProject}
                validations={validations}
                selectedVersion={selectedVersion}
                selectedStage={selectedStage}
                onSelectStage={setSelectedStage}
                isGenerating={isGenerating}
              />

              {/* Bottom Section: Artifact Studio & Deterministic Validation Engine */}
              <BottomCards
                artifact={currentArtifact}
                versions={versions}
                selectedVersion={selectedVersion}
                onSelectVersion={(vNum) => {
                  const v = versions.find((x) => x.version_number === vNum);
                  if (v) setSelectedVersion(v);
                }}
                validations={validations}
                onApprove={handleApprove}
                onRequestChanges={handleRequestChanges}
                onReject={handleReject}
                onOpenDiff={() => setShowDiffModal(true)}
              />
            </>
          )}

          {activeTab === 'traceability' && (
            <TraceabilityCard projectId={activeProject?.id} />
          )}

          {activeTab === 'deployment' && (
            <DeploymentPackageView
              projectId={activeProject?.id}
              workflowStages={workflowStages}
            />
          )}
          </>}
        </main>

        {/* Footer */}
        <Footer />
      </div>

      {/* Modals */}
      {showNewProjectModal && (
        <NewProjectModal
          erpProfiles={erpProfiles}
          onClose={() => setShowNewProjectModal(false)}
          onCreateProject={handleCreateProject}
        />
      )}

      {showDiffModal && currentArtifact && (
        <DiffViewer
          artifact={currentArtifact}
          versions={versions}
          onClose={() => setShowDiffModal(false)}
        />
      )}
    </div>
  );
}
